"""
Draft Response Generator for GMB Gorilla
Uses Claude API to generate draft responses matching GMB Gorilla's voice and processes
"""

import os
import anthropic
from dataclasses import dataclass
from typing import Optional


# GMB Gorilla System Prompt - based on Account Manager Handbook
SYSTEM_PROMPT = """You are an AI assistant helping draft customer responses for GMB Gorilla, a Google Business Profile management service. Your drafts will be reviewed by account managers before sending.

## GMB Gorilla Brand Voice
- Nerdy and nice, fun and friendly
- Professional but approachable
- You are an expert guide helping customers navigate the "digital jungle"
- Use occasional gorilla/jungle metaphors but don't overdo it
- Never use "Cheers" as a closing

## Message Format Rules
1. Always start with a greeting: "Hi {name}" or "Howdy {name}" or "Good morning/afternoon {name}"
2. Keep messages to 5 sentences or less when possible
3. Be direct and concise - most customers read on mobile
4. Use bullet points only when listing 3+ distinct items
5. End with a friendly closing: "Thanks!" or "All my best," or "Let me know if you have questions!"
6. Include your sign-off line if one is provided

## Services & Timelines (use when relevant)
- **Setup Service** ($350): 2-4 weeks to verify and set up listing
- **Optimization Service** ($350): 2-4 weeks, results in 30-90 days
- **Management Service** ($350/month): Initial optimization in first 30 days, then ongoing monthly management
- **Support Service** ($350/incident): For issues like suspensions, duplicates, recovery

## Service Stages (first 30 days of Management)
- Days 1-7 [Onboarding]: Intake form, location group ID, setup tools
- Days 8-15 [Audit]: 100-point audit, create scorecard
- Days 16-23 [Enhancement]: Create & implement optimization guide
- Days 24-30 [Management]: Posts, Q&A, review responses, service descriptions

## Common Response Scenarios

### Timeline Questions
"We're currently in the [stage] phase. You can expect [next milestone] within [timeframe]. Results from optimization typically show within 30-90 days."

### Status Updates
"Great news - we've completed [what was done]. Next up, we'll be [next step]. I'll send that over for your review by [date]."

### Edit Requests
"Got it! I'll make those changes to [item]. You should see the updates within [timeframe]."

### Asking for Information
"To move forward, I'll need [specific items]. Once I have those, I can [next action]."

### Results Questions
"Profile optimization results typically appear within 30-90 days as Google indexes the changes. We're monitoring your rankings via our geogrid reports."

## Handling Difficult Situations
- If client is frustrated: Acknowledge, apologize if warranted, provide clear next steps
- If you don't know something: Say "Let me check with the team and get back to you"
- If outside scope: Explain what is/isn't included, offer alternatives

## Do NOT:
- Make promises about specific ranking improvements
- Guarantee timelines that haven't been discussed
- Provide technical Google support advice (that's a separate service)
- Use excessive emojis (1-2 max, and only 🦍 or related)
- Write long paragraphs

## Draft Guidelines
Generate a natural, helpful response that:
1. Addresses the customer's specific question/concern
2. Provides clear, actionable information
3. Sets appropriate expectations
4. Maintains the friendly GMB Gorilla tone
5. Is concise enough to be read on mobile"""


@dataclass
class DraftResponse:
    """A generated draft response"""
    source_type: str  # 'order' or 'ticket'
    source_id: int
    client_name: str
    client_email: str
    service_name: str
    subject: str
    client_message: str
    conversation_history: list
    draft_response: str
    manager_user_id: Optional[int]
    confidence: str  # 'high', 'medium', 'low'
    notes: str  # AI notes for reviewer


class DraftGenerator:
    """Generates draft responses using Claude API"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable required")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"
    
    def _format_conversation_history(self, messages: list, client_user_id: int) -> str:
        """Format message history for context (oldest first)"""
        # Reverse to get chronological order
        messages_chrono = list(reversed(messages))
        
        formatted = []
        for msg in messages_chrono[-10:]:  # Last 10 messages max
            sender = "CLIENT" if msg.user_id == client_user_id else "STAFF"
            if msg.staff_only:
                sender = "STAFF (internal)"
            
            # Truncate very long messages
            content = msg.message
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            
            formatted.append(f"[{sender}]: {content}")
        
        return "\n\n".join(formatted)
    
    def _determine_confidence(self, response_text: str, notes: str) -> str:
        """Determine confidence level based on AI notes"""
        low_confidence_signals = [
            "not sure", "unclear", "need more", "check with",
            "might", "possibly", "complex", "escalate"
        ]
        
        notes_lower = notes.lower()
        for signal in low_confidence_signals:
            if signal in notes_lower:
                return "low"
        
        if len(response_text) > 400:  # Long responses might need review
            return "medium"
        
        return "high"
    
    def generate_draft(
        self,
        source_type: str,
        item,  # Order or Ticket
        messages: list,
        client_message,  # Message object
        manager_user_id: Optional[int] = None
    ) -> DraftResponse:
        """
        Generate a draft response for an order or ticket.
        
        Args:
            source_type: 'order' or 'ticket'
            item: Order or Ticket object
            messages: List of Message objects (newest first)
            client_message: The specific client message to respond to
            manager_user_id: ID of manager who will send the reply
        """
        # Build context
        client_name = item.client.full_name or item.client.name_f or "there"
        service_name = item.service if source_type == 'order' else "Support"
        subject = item.service if source_type == 'order' else item.subject
        
        conversation_history = self._format_conversation_history(messages, item.user_id)
        
        # Determine service stage based on order status if available
        stage_context = ""
        if source_type == 'order':
            status = item.status.lower()
            if 'pending' in status or 'submitted' in status:
                stage_context = "Customer is in ONBOARDING phase (Days 1-7)."
            elif 'working' in status or 'setup' in status:
                stage_context = "Customer is in SETUP/AUDIT phase (Days 8-15)."
            elif 'audit' in status:
                stage_context = "Customer is in AUDIT phase - audit should be sent soon."
            elif 'enhancement' in status:
                stage_context = "Customer is in ENHANCEMENT phase (Days 16-23)."
            elif 'management' in status or 'completed' in status:
                stage_context = "Customer is in ongoing MANAGEMENT phase."
        
        # Build prompt
        user_prompt = f"""Generate a draft response for this customer message.

## Context
- **Source**: {source_type.upper()} #{item.id}
- **Service**: {service_name}
- **Subject**: {subject}
- **Client Name**: {client_name}
- **Order Status**: {item.status}
{f'- **Stage**: {stage_context}' if stage_context else ''}
{f'- **Internal Note**: {item.note}' if item.note else ''}

## Conversation History
{conversation_history}

## Message to Reply To
{client_message.message}

---

Please provide:
1. A draft response following GMB Gorilla's voice and format guidelines
2. Brief notes for the reviewer (confidence level, anything to verify, suggested edits)

Format your response as:
DRAFT:
[your draft message here]

NOTES:
[your notes for the reviewer]"""

        # Call Claude API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        # Parse response
        full_response = response.content[0].text
        
        # Split into draft and notes
        draft_text = ""
        notes_text = ""
        
        if "DRAFT:" in full_response and "NOTES:" in full_response:
            parts = full_response.split("NOTES:")
            draft_text = parts[0].replace("DRAFT:", "").strip()
            notes_text = parts[1].strip() if len(parts) > 1 else ""
        else:
            draft_text = full_response
            notes_text = "No notes provided"
        
        confidence = self._determine_confidence(draft_text, notes_text)
        
        return DraftResponse(
            source_type=source_type,
            source_id=item.id,
            client_name=client_name,
            client_email=item.client.email,
            service_name=service_name,
            subject=subject,
            client_message=client_message.message,
            conversation_history=[{"sender": "client" if m.user_id == item.user_id else "staff", 
                                   "message": m.message, 
                                   "created_at": m.created_at.isoformat() if m.created_at else None}
                                  for m in messages],
            draft_response=draft_text,
            manager_user_id=manager_user_id,
            confidence=confidence,
            notes=notes_text
        )


if __name__ == "__main__":
    # Test with mock data
    generator = DraftGenerator()
    print("Draft generator initialized successfully")
    print(f"Using model: {generator.model}")
