"""
Supabase Database Client for SPP Auto-Reply
Handles all database operations for the draft queue
"""

import os
import hashlib
from datetime import datetime
from typing import Optional
from supabase import create_client, Client
from draft_generator import DraftResponse


class DatabaseClient:
    """Client for Supabase database operations"""
    
    def __init__(self, url: str = None, key: str = None):
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_KEY")
        
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables required")
        
        self.client: Client = create_client(self.url, self.key)
    
    # =========================================================================
    # Draft Responses
    # =========================================================================
    
    def create_draft(self, draft: DraftResponse, message_id: int = None) -> dict:
        """
        Save a draft response to the database.
        
        Args:
            draft: DraftResponse object from generator
            message_id: SPP message ID (for deduplication)
        
        Returns:
            Created record
        """
        data = {
            "source_type": draft.source_type,
            "source_id": draft.source_id,
            "client_name": draft.client_name,
            "client_email": draft.client_email,
            "service_name": draft.service_name,
            "subject": draft.subject,
            "client_message": draft.client_message,
            "client_message_id": message_id,
            "conversation_history": draft.conversation_history,
            "draft_response": draft.draft_response,
            "manager_user_id": draft.manager_user_id,
            "confidence": draft.confidence,
            "ai_notes": draft.notes,
            "status": "pending"
        }
        
        result = self.client.table("draft_responses").insert(data).execute()
        return result.data[0] if result.data else None
    
    def get_pending_drafts(self, limit: int = 50) -> list:
        """Get all pending drafts for the approval queue"""
        result = self.client.table("draft_responses") \
            .select("*") \
            .eq("status", "pending") \
            .order("created_at", desc=False) \
            .limit(limit) \
            .execute()
        
        return result.data
    
    def get_draft_by_id(self, draft_id: str) -> Optional[dict]:
        """Get a specific draft by ID"""
        result = self.client.table("draft_responses") \
            .select("*") \
            .eq("id", draft_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def approve_draft(
        self,
        draft_id: str,
        reviewed_by: str,
        edited_response: str = None,
        review_notes: str = None
    ) -> dict:
        """
        Approve a draft for sending.
        
        Args:
            draft_id: UUID of the draft
            reviewed_by: Name/email of reviewer
            edited_response: Modified response text (optional)
            review_notes: Notes from reviewer (optional)
        """
        data = {
            "status": "approved",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat(),
            "review_notes": review_notes
        }
        
        if edited_response:
            data["edited_response"] = edited_response
        
        result = self.client.table("draft_responses") \
            .update(data) \
            .eq("id", draft_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def reject_draft(
        self,
        draft_id: str,
        reviewed_by: str,
        review_notes: str = None
    ) -> dict:
        """Reject a draft (won't be sent)"""
        data = {
            "status": "rejected",
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.utcnow().isoformat(),
            "review_notes": review_notes
        }
        
        result = self.client.table("draft_responses") \
            .update(data) \
            .eq("id", draft_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def mark_sent(
        self,
        draft_id: str,
        spp_response: dict = None
    ) -> dict:
        """Mark a draft as successfully sent"""
        data = {
            "status": "sent",
            "sent_at": datetime.utcnow().isoformat(),
            "spp_response": spp_response
        }
        
        result = self.client.table("draft_responses") \
            .update(data) \
            .eq("id", draft_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def mark_send_error(
        self,
        draft_id: str,
        error_message: str
    ) -> dict:
        """Mark a draft as having a send error"""
        data = {
            "status": "error",
            "send_error": error_message
        }
        
        result = self.client.table("draft_responses") \
            .update(data) \
            .eq("id", draft_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def get_approved_drafts(self, limit: int = 50) -> list:
        """Get approved drafts ready to be sent"""
        result = self.client.table("draft_responses") \
            .select("*") \
            .eq("status", "approved") \
            .order("reviewed_at", desc=False) \
            .limit(limit) \
            .execute()
        
        return result.data
    
    # =========================================================================
    # Processed Messages (deduplication)
    # =========================================================================
    
    def is_message_processed(
        self,
        source_type: str,
        source_id: int,
        message_id: int
    ) -> bool:
        """Check if we've already processed this message"""
        result = self.client.table("processed_messages") \
            .select("id") \
            .eq("source_type", source_type) \
            .eq("source_id", source_id) \
            .eq("message_id", message_id) \
            .execute()
        
        return len(result.data) > 0
    
    def mark_message_processed(
        self,
        source_type: str,
        source_id: int,
        message_id: int,
        action: str,
        draft_id: str = None,
        skip_reason: str = None,
        error_message: str = None,
        message_content: str = None
    ) -> dict:
        """Record that we've processed a message"""
        data = {
            "source_type": source_type,
            "source_id": source_id,
            "message_id": message_id,
            "action": action,
            "draft_id": draft_id,
            "skip_reason": skip_reason,
            "error_message": error_message
        }
        
        # Add content hash for extra deduplication
        if message_content:
            data["message_hash"] = hashlib.md5(message_content.encode()).hexdigest()
        
        result = self.client.table("processed_messages").insert(data).execute()
        return result.data[0] if result.data else None
    
    # =========================================================================
    # Poller Runs (monitoring)
    # =========================================================================
    
    def start_poller_run(self) -> str:
        """Record the start of a poller run, returns run ID"""
        result = self.client.table("poller_runs") \
            .insert({"status": "running"}) \
            .execute()
        
        return result.data[0]["id"] if result.data else None
    
    def complete_poller_run(
        self,
        run_id: str,
        orders_checked: int = 0,
        tickets_checked: int = 0,
        items_needing_reply: int = 0,
        drafts_created: int = 0,
        errors: int = 0,
        error_log: list = None
    ) -> dict:
        """Record the completion of a poller run"""
        data = {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "orders_checked": orders_checked,
            "tickets_checked": tickets_checked,
            "items_needing_reply": items_needing_reply,
            "drafts_created": drafts_created,
            "errors": errors,
            "error_log": error_log or []
        }
        
        result = self.client.table("poller_runs") \
            .update(data) \
            .eq("id", run_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def fail_poller_run(self, run_id: str, error_message: str) -> dict:
        """Record a failed poller run"""
        data = {
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error_log": [{"error": error_message, "timestamp": datetime.utcnow().isoformat()}]
        }
        
        result = self.client.table("poller_runs") \
            .update(data) \
            .eq("id", run_id) \
            .execute()
        
        return result.data[0] if result.data else None
    
    # =========================================================================
    # Settings
    # =========================================================================
    
    def get_setting(self, key: str, default=None):
        """Get a setting value"""
        result = self.client.table("settings") \
            .select("value") \
            .eq("key", key) \
            .execute()
        
        if result.data:
            return result.data[0]["value"]
        return default
    
    def set_setting(self, key: str, value) -> dict:
        """Set a setting value"""
        result = self.client.table("settings") \
            .upsert({"key": key, "value": value}) \
            .execute()
        
        return result.data[0] if result.data else None
    
    # =========================================================================
    # Stats
    # =========================================================================
    
    def get_stats(self, hours: int = 24) -> dict:
        """Get statistics for the dashboard"""
        # Count by status
        pending = self.client.table("draft_responses") \
            .select("id", count="exact") \
            .eq("status", "pending") \
            .execute()
        
        approved = self.client.table("draft_responses") \
            .select("id", count="exact") \
            .eq("status", "approved") \
            .execute()
        
        sent = self.client.table("draft_responses") \
            .select("id", count="exact") \
            .eq("status", "sent") \
            .execute()
        
        rejected = self.client.table("draft_responses") \
            .select("id", count="exact") \
            .eq("status", "rejected") \
            .execute()
        
        return {
            "pending": pending.count or 0,
            "approved": approved.count or 0,
            "sent": sent.count or 0,
            "rejected": rejected.count or 0
        }


if __name__ == "__main__":
    # Quick test
    db = DatabaseClient()
    print("Database client initialized successfully")
    
    stats = db.get_stats()
    print(f"Current stats: {stats}")
