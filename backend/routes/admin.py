"""ComplyChip V3 - Admin Routes"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.dependencies import require_roles
from backend.services.firestore_service import get_documents

router = APIRouter()


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_users() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "demo-admin-001",
            "email": "admin@complychip.ai",
            "name": "Admin User",
            "role": "admin",
            "is_active": True,
            "organization_id": "demo-org-001",
            "last_login": (now - timedelta(hours=1)).isoformat(),
            "created_at": (now - timedelta(days=365)).isoformat(),
        },
        {
            "id": "user-002",
            "email": "sarah.chen@complychip.ai",
            "name": "Sarah Chen",
            "role": "manager",
            "is_active": True,
            "organization_id": "demo-org-001",
            "last_login": (now - timedelta(hours=4)).isoformat(),
            "created_at": (now - timedelta(days=200)).isoformat(),
        },
        {
            "id": "user-003",
            "email": "james.wilson@complychip.ai",
            "name": "James Wilson",
            "role": "analyst",
            "is_active": True,
            "organization_id": "demo-org-001",
            "last_login": (now - timedelta(days=1)).isoformat(),
            "created_at": (now - timedelta(days=150)).isoformat(),
        },
        {
            "id": "user-004",
            "email": "maria.garcia@complychip.ai",
            "name": "Maria Garcia",
            "role": "viewer",
            "is_active": True,
            "organization_id": "demo-org-001",
            "last_login": (now - timedelta(days=3)).isoformat(),
            "created_at": (now - timedelta(days=90)).isoformat(),
        },
        {
            "id": "user-005",
            "email": "robert.lee@complychip.ai",
            "name": "Robert Lee",
            "role": "analyst",
            "is_active": False,
            "organization_id": "demo-org-001",
            "last_login": (now - timedelta(days=45)).isoformat(),
            "created_at": (now - timedelta(days=300)).isoformat(),
        },
    ]


def _demo_audit_log() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "audit-001",
            "timestamp": (now - timedelta(minutes=15)).isoformat(),
            "user_id": "demo-admin-001",
            "user_email": "admin@complychip.ai",
            "action": "document.upload",
            "resource_type": "document",
            "resource_id": "doc-010",
            "details": "Uploaded 'Subcontractor Agreement - QuickBuild Contractors'",
            "ip_address": "192.168.1.100",
        },
        {
            "id": "audit-002",
            "timestamp": (now - timedelta(minutes=45)).isoformat(),
            "user_id": "user-002",
            "user_email": "sarah.chen@complychip.ai",
            "action": "document.approve",
            "resource_type": "document",
            "resource_id": "doc-005",
            "details": "Approved 'Mutual NDA - TechServe Solutions'",
            "ip_address": "192.168.1.101",
        },
        {
            "id": "audit-003",
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "user_id": "demo-admin-001",
            "user_email": "admin@complychip.ai",
            "action": "entity.create",
            "resource_type": "entity",
            "resource_id": "entity-004",
            "details": "Created entity 'Riverside Tower'",
            "ip_address": "192.168.1.100",
        },
        {
            "id": "audit-004",
            "timestamp": (now - timedelta(hours=5)).isoformat(),
            "user_id": "user-003",
            "user_email": "james.wilson@complychip.ai",
            "action": "compliance.recalculate",
            "resource_type": "entity",
            "resource_id": "entity-001",
            "details": "Recalculated compliance score for 'Sunrise Properties LLC'",
            "ip_address": "192.168.1.102",
        },
        {
            "id": "audit-005",
            "timestamp": (now - timedelta(hours=8)).isoformat(),
            "user_id": "demo-admin-001",
            "user_email": "admin@complychip.ai",
            "action": "user.create",
            "resource_type": "user",
            "resource_id": "user-004",
            "details": "Created user account for 'Maria Garcia'",
            "ip_address": "192.168.1.100",
        },
        {
            "id": "audit-006",
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "user_id": "user-002",
            "user_email": "sarah.chen@complychip.ai",
            "action": "vendor.update",
            "resource_type": "vendor",
            "resource_id": "vendor-006",
            "details": "Updated 'QuickBuild Contractors' status to under_review",
            "ip_address": "192.168.1.101",
        },
        {
            "id": "audit-007",
            "timestamp": (now - timedelta(days=1, hours=4)).isoformat(),
            "user_id": "demo-admin-001",
            "user_email": "admin@complychip.ai",
            "action": "rule.create",
            "resource_type": "compliance_rule",
            "resource_id": "rule-008",
            "details": "Created compliance rule 'Data Processing Agreement'",
            "ip_address": "192.168.1.100",
        },
        {
            "id": "audit-008",
            "timestamp": (now - timedelta(days=2)).isoformat(),
            "user_id": "user-003",
            "user_email": "james.wilson@complychip.ai",
            "action": "document.reject",
            "resource_type": "document",
            "resource_id": "doc-010",
            "details": "Rejected 'Subcontractor Agreement - QuickBuild Contractors' - missing indemnification clause",
            "ip_address": "192.168.1.102",
        },
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_roles("admin")),
):
    """List all users (admin only)."""
    try:
        org_id = user.get("org_id", "")
        filters = []
        if org_id:
            filters.append(("organization_id", "==", org_id))
        if role:
            filters.append(("role", "==", role))
        if active_only:
            filters.append(("is_active", "==", True))
        users = get_documents("users", filters=filters if filters else None, limit=limit * page)
        if users:
            # Strip password hashes from response
            for u in users:
                u.pop("password", None)
            total = len(users)
            start = (page - 1) * limit
            users = users[start:start + limit]
            return {"users": users, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback
    demos = _demo_users()
    if role:
        demos = [u for u in demos if u["role"] == role]
    if active_only:
        demos = [u for u in demos if u.get("is_active", True)]
    total = len(demos)
    start = (page - 1) * limit
    demos = demos[start:start + limit]
    return {"users": demos, "total": total, "page": page, "limit": limit}


@router.get("/audit-log")
async def get_audit_log(
    action: Optional[str] = Query(None),
    user_id_filter: Optional[str] = Query(None, alias="user_id"),
    resource_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_roles("admin")),
):
    """Get the audit log (admin only)."""
    try:
        filters = []
        org_id = user.get("org_id", "")
        if org_id:
            filters.append(("organization_id", "==", org_id))
        if action:
            filters.append(("action", "==", action))
        if user_id_filter:
            filters.append(("user_id", "==", user_id_filter))
        if resource_type:
            filters.append(("resource_type", "==", resource_type))
        logs = get_documents(
            "audit_log",
            filters=filters if filters else None,
            order_by="timestamp",
            direction="DESCENDING",
            limit=limit * page,
        )
        if logs:
            total = len(logs)
            start = (page - 1) * limit
            logs = logs[start:start + limit]
            return {"audit_log": logs, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback
    demos = _demo_audit_log()
    if action:
        demos = [l for l in demos if l["action"] == action]
    if user_id_filter:
        demos = [l for l in demos if l["user_id"] == user_id_filter]
    if resource_type:
        demos = [l for l in demos if l["resource_type"] == resource_type]
    total = len(demos)
    start = (page - 1) * limit
    demos = demos[start:start + limit]
    return {"audit_log": demos, "total": total, "page": page, "limit": limit}
