#!/usr/bin/env python3
"""
SPP Auto-Reply Approval UI
Simple web interface for reviewing and approving draft responses

Run locally:
python approval_server.py

Then open: http://localhost:8000
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import DatabaseClient
from spp_client import SPPClient


app = FastAPI(title="SPP Auto-Reply Approval Queue")

# Initialize clients
db = DatabaseClient()
spp = SPPClient()


# ============================================================================
# API Models
# ============================================================================

class ApproveRequest(BaseModel):
    reviewed_by: str
    edited_response: Optional[str] = None
    review_notes: Optional[str] = None


class RejectRequest(BaseModel):
    reviewed_by: str
    review_notes: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/drafts")
def get_pending_drafts():
    """Get all pending drafts for the queue"""
    drafts = db.get_pending_drafts(limit=100)
    return {"drafts": drafts, "count": len(drafts)}


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: str):
    """Get a specific draft"""
    draft = db.get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, request: ApproveRequest):
    """Approve a draft for sending"""
    draft = db.get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft['status'] != 'pending':
        raise HTTPException(status_code=400, detail=f"Draft is already {draft['status']}")
    
    # Approve it
    updated = db.approve_draft(
        draft_id=draft_id,
        reviewed_by=request.reviewed_by,
        edited_response=request.edited_response,
        review_notes=request.review_notes
    )
    
    return {"status": "approved", "draft": updated}


@app.post("/api/drafts/{draft_id}/approve-and-send")
def approve_and_send_draft(draft_id: str, request: ApproveRequest):
    """Approve and immediately send a draft"""
    draft = db.get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft['status'] != 'pending':
        raise HTTPException(status_code=400, detail=f"Draft is already {draft['status']}")
    
    # Approve it
    db.approve_draft(
        draft_id=draft_id,
        reviewed_by=request.reviewed_by,
        edited_response=request.edited_response,
        review_notes=request.review_notes
    )
    
    # Send it
    message_to_send = request.edited_response or draft['draft_response']
    
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
        
        db.mark_sent(draft_id, spp_response=response)
        return {"status": "sent", "spp_response": response}
        
    except Exception as e:
        db.mark_send_error(draft_id, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, request: RejectRequest):
    """Reject a draft"""
    draft = db.get_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft['status'] != 'pending':
        raise HTTPException(status_code=400, detail=f"Draft is already {draft['status']}")
    
    updated = db.reject_draft(
        draft_id=draft_id,
        reviewed_by=request.reviewed_by,
        review_notes=request.review_notes
    )
    
    return {"status": "rejected", "draft": updated}


@app.get("/api/stats")
def get_stats():
    """Get queue statistics"""
    return db.get_stats()


@app.post("/api/send-approved")
def send_all_approved():
    """Send all approved drafts"""
    approved = db.get_approved_drafts()
    results = {"sent": 0, "errors": []}
    
    for draft in approved:
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
            results["sent"] += 1
            
        except Exception as e:
            db.mark_send_error(draft['id'], str(e))
            results["errors"].append({"id": draft['id'], "error": str(e)})
    
    return results


# ============================================================================
# HTML UI
# ============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPP Auto-Reply Queue</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div x-data="queueApp()" x-init="loadDrafts()" class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex justify-between items-center mb-8">
            <div>
                <h1 class="text-3xl font-bold text-gray-800">🦍 GMB Gorilla Response Queue</h1>
                <p class="text-gray-600 mt-1">Review and approve AI-generated responses</p>
            </div>
            <div class="flex gap-4">
                <div class="text-center px-4 py-2 bg-yellow-100 rounded-lg">
                    <div class="text-2xl font-bold text-yellow-700" x-text="stats.pending"></div>
                    <div class="text-sm text-yellow-600">Pending</div>
                </div>
                <div class="text-center px-4 py-2 bg-green-100 rounded-lg">
                    <div class="text-2xl font-bold text-green-700" x-text="stats.sent"></div>
                    <div class="text-sm text-green-600">Sent Today</div>
                </div>
                <button @click="loadDrafts()" class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600">
                    ↻ Refresh
                </button>
            </div>
        </div>

        <!-- Queue -->
        <div class="space-y-4">
            <template x-for="draft in drafts" :key="draft.id">
                <div class="bg-white rounded-lg shadow-md overflow-hidden">
                    <!-- Header -->
                    <div class="px-6 py-4 bg-gray-50 border-b flex justify-between items-center">
                        <div>
                            <span class="text-sm font-medium text-gray-500" x-text="draft.source_type.toUpperCase()"></span>
                            <span class="text-sm text-gray-400">#</span>
                            <span class="text-sm font-mono text-gray-600" x-text="draft.source_id"></span>
                            <span class="mx-2 text-gray-300">|</span>
                            <span class="font-semibold text-gray-800" x-text="draft.client_name"></span>
                            <span class="mx-2 text-gray-300">|</span>
                            <span class="text-sm text-gray-600" x-text="draft.service_name || draft.subject"></span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="px-2 py-1 text-xs rounded-full"
                                  :class="{
                                      'bg-green-100 text-green-800': draft.confidence === 'high',
                                      'bg-yellow-100 text-yellow-800': draft.confidence === 'medium',
                                      'bg-red-100 text-red-800': draft.confidence === 'low'
                                  }"
                                  x-text="draft.confidence + ' confidence'"></span>
                            <span class="text-xs text-gray-400" x-text="formatTime(draft.created_at)"></span>
                        </div>
                    </div>
                    
                    <!-- Content -->
                    <div class="px-6 py-4">
                        <!-- Client Message -->
                        <div class="mb-4">
                            <div class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Client Message</div>
                            <div class="bg-blue-50 p-3 rounded-lg text-gray-700" x-text="draft.client_message"></div>
                        </div>
                        
                        <!-- Draft Response -->
                        <div class="mb-4">
                            <div class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Draft Response</div>
                            <textarea 
                                class="w-full p-3 border rounded-lg text-gray-700 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                rows="4"
                                x-model="draft.edited_response"
                                x-text="draft.draft_response"
                            ></textarea>
                        </div>
                        
                        <!-- AI Notes -->
                        <div x-show="draft.ai_notes" class="mb-4">
                            <div class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">AI Notes</div>
                            <div class="bg-gray-50 p-3 rounded-lg text-sm text-gray-600" x-text="draft.ai_notes"></div>
                        </div>
                    </div>
                    
                    <!-- Actions -->
                    <div class="px-6 py-4 bg-gray-50 border-t flex justify-end gap-3">
                        <button 
                            @click="rejectDraft(draft)"
                            class="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors">
                            ✕ Reject
                        </button>
                        <button 
                            @click="approveDraft(draft)"
                            class="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors">
                            ✓ Approve
                        </button>
                        <button 
                            @click="approveAndSend(draft)"
                            class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors">
                            ✓ Approve & Send
                        </button>
                    </div>
                </div>
            </template>
            
            <!-- Empty State -->
            <div x-show="drafts.length === 0" class="text-center py-12">
                <div class="text-6xl mb-4">🦍</div>
                <div class="text-xl text-gray-600">No pending drafts</div>
                <div class="text-gray-500">All caught up! New drafts will appear here.</div>
            </div>
        </div>
    </div>

    <script>
        function queueApp() {
            return {
                drafts: [],
                stats: { pending: 0, sent: 0, approved: 0, rejected: 0 },
                reviewerName: localStorage.getItem('reviewerName') || '',
                
                async loadDrafts() {
                    try {
                        const response = await fetch('/api/drafts');
                        const data = await response.json();
                        this.drafts = data.drafts.map(d => ({
                            ...d,
                            edited_response: d.draft_response
                        }));
                        
                        const statsResponse = await fetch('/api/stats');
                        this.stats = await statsResponse.json();
                    } catch (e) {
                        console.error('Failed to load drafts:', e);
                    }
                },
                
                getReviewerName() {
                    if (!this.reviewerName) {
                        this.reviewerName = prompt('Enter your name for the review log:') || 'Unknown';
                        localStorage.setItem('reviewerName', this.reviewerName);
                    }
                    return this.reviewerName;
                },
                
                async approveDraft(draft) {
                    const reviewer = this.getReviewerName();
                    try {
                        await fetch(`/api/drafts/${draft.id}/approve`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                reviewed_by: reviewer,
                                edited_response: draft.edited_response !== draft.draft_response ? draft.edited_response : null
                            })
                        });
                        this.drafts = this.drafts.filter(d => d.id !== draft.id);
                        this.stats.pending--;
                        this.stats.approved++;
                    } catch (e) {
                        alert('Failed to approve: ' + e.message);
                    }
                },
                
                async approveAndSend(draft) {
                    const reviewer = this.getReviewerName();
                    try {
                        const response = await fetch(`/api/drafts/${draft.id}/approve-and-send`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                reviewed_by: reviewer,
                                edited_response: draft.edited_response !== draft.draft_response ? draft.edited_response : null
                            })
                        });
                        if (!response.ok) {
                            const error = await response.json();
                            throw new Error(error.detail);
                        }
                        this.drafts = this.drafts.filter(d => d.id !== draft.id);
                        this.stats.pending--;
                        this.stats.sent++;
                    } catch (e) {
                        alert('Failed to send: ' + e.message);
                    }
                },
                
                async rejectDraft(draft) {
                    const reviewer = this.getReviewerName();
                    const reason = prompt('Reason for rejection (optional):');
                    try {
                        await fetch(`/api/drafts/${draft.id}/reject`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                reviewed_by: reviewer,
                                review_notes: reason
                            })
                        });
                        this.drafts = this.drafts.filter(d => d.id !== draft.id);
                        this.stats.pending--;
                        this.stats.rejected++;
                    } catch (e) {
                        alert('Failed to reject: ' + e.message);
                    }
                },
                
                formatTime(isoString) {
                    const date = new Date(isoString);
                    return date.toLocaleString();
                }
            }
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    """Serve the approval UI"""
    return HTML_TEMPLATE


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
