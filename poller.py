#!/usr/bin/env python3
"""
SPP Auto-Reply Poller
Checks for new messages needing replies and generates drafts

Run hourly via cron:
0 9-17 * * 1-5 cd /path/to/spp-auto-reply && python poller.py

Or manually:
python poller.py
python poller.py --hours 48  # Look back 48 hours
python poller.py --dry-run   # Don't save drafts, just log
"""

import argparse
import logging
from datetime import datetime

from spp_client import SPPClient
from draft_generator import DraftGenerator
from database import DatabaseClient


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_poller(hours_lookback: int = 24, dry_run: bool = False):
    """
    Main poller function.
    
    1. Connects to SPP API
    2. Finds orders/tickets where last message is from client
    3. Generates draft responses
    4. Saves to database queue
    """
    logger.info(f"Starting poller run (lookback={hours_lookback}h, dry_run={dry_run})")
    
    # Initialize clients
    spp = SPPClient()
    generator = DraftGenerator()
    db = DatabaseClient() if not dry_run else None
    
    # Start tracking this run
    run_id = db.start_poller_run() if db else None
    
    stats = {
        "orders_checked": 0,
        "tickets_checked": 0,
        "items_needing_reply": 0,
        "drafts_created": 0,
        "skipped": 0,
        "errors": 0
    }
    error_log = []
    
    try:
        # Find items needing reply
        logger.info("Fetching orders and tickets needing reply...")
        items = spp.find_items_needing_reply(
            check_orders=True,
            check_tickets=True,
            hours_lookback=hours_lookback
        )
        
        stats["items_needing_reply"] = len(items)
        logger.info(f"Found {len(items)} items needing reply")
        
        # Process each item
        for item_data in items:
            source_type = item_data['type']
            item = item_data['item']
            messages = item_data['messages']
            client_message = item_data['client_message']
            manager_user_id = item_data['manager_user_id']
            
            logger.info(f"Processing {source_type} #{item.id} from {item.client.full_name}")
            
            # Track stats
            if source_type == 'order':
                stats["orders_checked"] += 1
            else:
                stats["tickets_checked"] += 1
            
            # Check if already processed
            if db and db.is_message_processed(source_type, item.id, client_message.id):
                logger.info(f"  Skipping - already processed message #{client_message.id}")
                stats["skipped"] += 1
                continue
            
            try:
                # Generate draft
                logger.info(f"  Generating draft response...")
                draft = generator.generate_draft(
                    source_type=source_type,
                    item=item,
                    messages=messages,
                    client_message=client_message,
                    manager_user_id=manager_user_id
                )
                
                logger.info(f"  Generated draft (confidence: {draft.confidence})")
                logger.debug(f"  Draft: {draft.draft_response[:100]}...")
                
                if dry_run:
                    logger.info(f"  [DRY RUN] Would save draft")
                    print(f"\n{'='*60}")
                    print(f"Draft for {source_type} #{item.id}")
                    print(f"Client: {draft.client_name}")
                    print(f"Message: {client_message.message[:100]}...")
                    print(f"{'='*60}")
                    print(draft.draft_response)
                    print(f"{'='*60}")
                    print(f"AI Notes: {draft.notes}")
                    print(f"Confidence: {draft.confidence}")
                    stats["drafts_created"] += 1
                else:
                    # Save to database
                    saved_draft = db.create_draft(draft, message_id=client_message.id)
                    
                    if saved_draft:
                        logger.info(f"  Saved draft {saved_draft['id']}")
                        stats["drafts_created"] += 1
                        
                        # Mark message as processed
                        db.mark_message_processed(
                            source_type=source_type,
                            source_id=item.id,
                            message_id=client_message.id,
                            action="draft_created",
                            draft_id=saved_draft['id'],
                            message_content=client_message.message
                        )
                    else:
                        logger.warning(f"  Failed to save draft")
                        stats["errors"] += 1
                        
            except Exception as e:
                logger.error(f"  Error generating draft: {e}")
                stats["errors"] += 1
                error_log.append({
                    "source_type": source_type,
                    "source_id": item.id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                if db:
                    db.mark_message_processed(
                        source_type=source_type,
                        source_id=item.id,
                        message_id=client_message.id,
                        action="error",
                        error_message=str(e)
                    )
        
        # Complete the run
        if db and run_id:
            db.complete_poller_run(
                run_id=run_id,
                orders_checked=stats["orders_checked"],
                tickets_checked=stats["tickets_checked"],
                items_needing_reply=stats["items_needing_reply"],
                drafts_created=stats["drafts_created"],
                errors=stats["errors"],
                error_log=error_log
            )
        
        logger.info(f"Poller run complete: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Poller run failed: {e}")
        if db and run_id:
            db.fail_poller_run(run_id, str(e))
        raise


def send_approved_drafts():
    """
    Send all approved drafts to SPP.
    
    This can be run separately or as part of the poller.
    """
    logger.info("Sending approved drafts...")
    
    spp = SPPClient()
    db = DatabaseClient()
    
    approved = db.get_approved_drafts()
    logger.info(f"Found {len(approved)} approved drafts to send")
    
    sent_count = 0
    error_count = 0
    
    for draft in approved:
        logger.info(f"Sending draft {draft['id']} to {draft['source_type']} #{draft['source_id']}")
        
        # Use edited response if available, otherwise original draft
        message_to_send = draft.get('edited_response') or draft['draft_response']
        
        try:
            if draft['source_type'] == 'order':
                response = spp.send_order_message(
                    order_id=draft['source_id'],
                    message=message_to_send,
                    user_id=draft.get('manager_user_id'),
                    staff_only=False
                )
            else:
                response = spp.send_ticket_message(
                    ticket_id=draft['source_id'],
                    message=message_to_send,
                    user_id=draft.get('manager_user_id'),
                    staff_only=False
                )
            
            db.mark_sent(draft['id'], spp_response=response)
            logger.info(f"  Sent successfully")
            sent_count += 1
            
        except Exception as e:
            logger.error(f"  Error sending: {e}")
            db.mark_send_error(draft['id'], str(e))
            error_count += 1
    
    logger.info(f"Sending complete: {sent_count} sent, {error_count} errors")
    return {"sent": sent_count, "errors": error_count}


def main():
    parser = argparse.ArgumentParser(description="SPP Auto-Reply Poller")
    parser.add_argument(
        "--hours", 
        type=int, 
        default=24,
        help="Hours to look back for messages (default: 24)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save drafts, just print them"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send approved drafts instead of polling"
    )
    
    args = parser.parse_args()
    
    if args.send:
        send_approved_drafts()
    else:
        run_poller(hours_lookback=args.hours, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
