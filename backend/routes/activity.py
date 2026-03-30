"""ComplyChip V3 - Activity Tracking Routes

Provides endpoints for logging user activity events and retrieving
activity feeds and summaries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import (
    create_document, get_documents, query_documents,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ActivityEvent(BaseModel):
    action: str  # "page_view", "document_open", "document_upload", "search", "analyze", "login", "logout"
    resource_type: str = ""  # "page", "document", "entity", etc.
    resource_id: str = ""
    details: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def log_activity(body: ActivityEvent, request: Request,
                       user: dict = Depends(get_current_user)):
    """Log a user activity event."""
    activity_data = {
        "user_id": user["user_id"],
        "action": body.action,
        "resource_type": body.resource_type,
        "resource_id": body.resource_id,
        "details": body.details,
        "ip_address": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("User-Agent", ""),
        "timestamp": datetime.now(timezone.utc),
    }
    doc_id = create_document("user_activities", activity_data)
    return {"message": "Activity logged", "activity_id": doc_id}


@router.get("")
async def get_activities(user: dict = Depends(get_current_user),
                         limit: int = 50, offset: int = 0):
    """Get activity feed for the current user (paginated, most recent first)."""
    activities = get_documents(
        "user_activities",
        filters=[("user_id", "==", user["user_id"])],
        limit=limit + offset + 200,  # over-fetch then sort in Python
    )
    # Sort by timestamp descending (avoids Firestore composite index requirement)
    activities.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    page = activities[offset:offset + limit]
    return {
        "activities": page,
        "total": len(activities),
        "limit": limit,
        "offset": offset,
    }


@router.get("/summary")
async def get_activity_summary(user: dict = Depends(get_current_user)):
    """Get activity summary for the current user (counts by action type)."""
    # Get all activities for today
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    all_activities = query_documents(
        "user_activities", "user_id", "==", user["user_id"]
    )

    # Count totals and today's counts
    total_counts: dict = {}
    today_counts: dict = {}

    for a in all_activities:
        action = a.get("action", "unknown")
        total_counts[action] = total_counts.get(action, 0) + 1

        # Check if activity is from today
        ts = a.get("timestamp", "")
        if isinstance(ts, str) and ts:
            try:
                activity_time = datetime.fromisoformat(ts)
                if activity_time.tzinfo is None:
                    activity_time = activity_time.replace(tzinfo=timezone.utc)
                if activity_time >= today_start:
                    today_counts[action] = today_counts.get(action, 0) + 1
            except (ValueError, TypeError):
                pass

    return {
        "user_id": user["user_id"],
        "today": today_counts,
        "all_time": total_counts,
        "total_activities": len(all_activities),
    }
