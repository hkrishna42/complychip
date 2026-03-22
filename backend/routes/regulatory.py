"""ComplyChip V3 - Regulatory Intelligence Routes"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import get_document, update_document
from backend.services.regulatory_service import (
    get_regulatory_feed,
    match_alerts_to_entities,
)

router = APIRouter()


class AlertStatusUpdate(BaseModel):
    status: str  # new, reviewed, acknowledged, resolved, dismissed


@router.get("/feed")
async def list_regulatory_alerts(
    jurisdiction: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get the regulatory alerts feed."""
    org_id = user.get("org_id", "") or "demo-org-001"
    alerts = get_regulatory_feed(org_id, jurisdiction=jurisdiction, limit=limit)

    if severity:
        alerts = [a for a in alerts if a.get("severity") == severity]
    if status:
        alerts = [a for a in alerts if a.get("status") == status]

    return {"alerts": alerts, "count": len(alerts)}


@router.get("/feed/{alert_id}")
async def get_alert_detail(alert_id: str, user: dict = Depends(get_current_user)):
    """Get details for a specific regulatory alert, including affected entities."""
    # Try Firestore first
    try:
        alert = get_document("regulatory_alerts", alert_id)
        if alert:
            match_data = match_alerts_to_entities(alert_id)
            alert["affected_entities"] = match_data.get("affected_entities", [])
            return alert
    except Exception:
        pass

    # Demo fallback
    feed = get_regulatory_feed("demo-org-001")
    for a in feed:
        if a.get("id") == alert_id:
            match_data = match_alerts_to_entities(alert_id)
            a["affected_entities"] = match_data.get("affected_entities", [])
            return a

    raise HTTPException(status_code=404, detail="Alert not found")


@router.put("/feed/{alert_id}")
async def update_alert_status(
    alert_id: str,
    body: AlertStatusUpdate,
    user: dict = Depends(get_current_user),
):
    """Update the status of a regulatory alert."""
    valid_statuses = {"new", "reviewed", "acknowledged", "resolved", "dismissed"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}",
        )

    try:
        success = update_document("regulatory_alerts", alert_id, {
            "status": body.status,
            "status_updated_by": user["user_id"],
        })
        if success:
            return {"message": "Alert status updated", "alert_id": alert_id, "status": body.status}
    except Exception:
        pass

    return {"message": "Alert status updated (demo)", "alert_id": alert_id, "status": body.status}
