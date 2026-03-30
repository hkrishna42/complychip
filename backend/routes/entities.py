"""ComplyChip V3 - Entity Routes"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import (
    get_document,
    get_documents,
    create_document,
    update_document,
    get_entity_documents,
    query_documents,
)
from backend.services.scoring_service import (
    calculate_entity_score,
    get_score_breakdown,
)

router = APIRouter()


def _score_to_risk(score: float) -> str:
    """Derive risk_level from compliance_score."""
    if score >= 85:
        return "low"
    if score >= 65:
        return "medium"
    if score >= 45:
        return "high"
    return "critical"


def _enrich_entity(e: dict) -> dict:
    """Add computed fields (document_count, risk_level) if missing."""
    score = e.get("compliance_score", 0)
    if not e.get("risk_level"):
        e["risk_level"] = _score_to_risk(score)
    if e.get("document_count") is None:
        # Count documents for this entity
        try:
            docs = query_documents("documents", "entity_id", "==", e.get("id", ""))
            e["document_count"] = len(docs)
        except Exception:
            e["document_count"] = 0
    return e


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EntityCreate(BaseModel):
    name: str
    entity_type: str = "property"
    address: Optional[str] = None
    jurisdiction: Optional[str] = None
    metadata: Optional[dict] = None


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    entity_type: Optional[str] = None
    address: Optional[str] = None
    jurisdiction: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_entities() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "entity-001",
            "name": "Sunrise Properties LLC",
            "entity_type": "property",
            "address": "1200 Ocean Blvd, Santa Monica, CA 90401",
            "jurisdiction": "State of California",
            "status": "active",
            "compliance_score": 73.5,
            "risk_level": "medium",
            "document_count": 5,
            "organization_id": "demo-org-001",
            "created_at": (now - timedelta(days=450)).isoformat(),
            "updated_at": (now - timedelta(days=5)).isoformat(),
        },
        {
            "id": "entity-002",
            "name": "Harbor View Complex",
            "entity_type": "property",
            "address": "500 Harbor Dr, San Diego, CA 92101",
            "jurisdiction": "State of California",
            "status": "active",
            "compliance_score": 88.2,
            "risk_level": "low",
            "document_count": 4,
            "organization_id": "demo-org-001",
            "created_at": (now - timedelta(days=300)).isoformat(),
            "updated_at": (now - timedelta(days=2)).isoformat(),
        },
        {
            "id": "entity-003",
            "name": "Oakmont Residences",
            "entity_type": "property",
            "address": "789 Oakmont Ave, Portland, OR 97205",
            "jurisdiction": "State of Oregon",
            "status": "active",
            "compliance_score": 56.0,
            "risk_level": "high",
            "document_count": 3,
            "organization_id": "demo-org-001",
            "created_at": (now - timedelta(days=600)).isoformat(),
            "updated_at": (now - timedelta(days=15)).isoformat(),
        },
        {
            "id": "entity-004",
            "name": "Riverside Tower",
            "entity_type": "property",
            "address": "350 River Rd, Austin, TX 78701",
            "jurisdiction": "State of Texas",
            "status": "active",
            "compliance_score": 92.1,
            "risk_level": "low",
            "document_count": 6,
            "organization_id": "demo-org-001",
            "created_at": (now - timedelta(days=180)).isoformat(),
            "updated_at": (now - timedelta(days=1)).isoformat(),
        },
        {
            "id": "entity-005",
            "name": "Metro Heights",
            "entity_type": "property",
            "address": "42 Broadway, New York, NY 10006",
            "jurisdiction": "State of New York",
            "status": "inactive",
            "compliance_score": 41.0,
            "risk_level": "critical",
            "document_count": 2,
            "organization_id": "demo-org-001",
            "created_at": (now - timedelta(days=900)).isoformat(),
            "updated_at": (now - timedelta(days=60)).isoformat(),
        },
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_entities(
    entity_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """List entities with optional filters and pagination."""
    try:
        filters = []
        is_admin = user.get("role") == "admin"
        org_id = user.get("org_id", "")
        # Non-admin users: filter by org and their own entities
        if not is_admin:
            if org_id:
                filters.append(("organization_id", "==", org_id))
            filters.append(("created_by", "==", user["user_id"]))
        if entity_type:
            filters.append(("entity_type", "==", entity_type))
        if status:
            filters.append(("status", "==", status))
        entities = get_documents("entities", filters=filters if filters else None, limit=limit * page)
        if entities:
            entities = [_enrich_entity(e) for e in entities]
            if search:
                s = search.lower()
                entities = [e for e in entities if s in e.get("name", "").lower() or s in e.get("address", "").lower()]
            total = len(entities)
            start = (page - 1) * limit
            entities = entities[start:start + limit]
            return {"entities": entities, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback — only show demo data for admin users
    if user.get("role") == "admin":
        demos = _demo_entities()
        if entity_type:
            demos = [e for e in demos if e["entity_type"] == entity_type]
        if status:
            demos = [e for e in demos if e["status"] == status]
        if search:
            s = search.lower()
            demos = [e for e in demos if s in e["name"].lower() or s in e.get("address", "").lower()]
        total = len(demos)
        start = (page - 1) * limit
        demos = demos[start:start + limit]
        return {"entities": demos, "total": total, "page": page, "limit": limit}
    return {"entities": [], "total": 0, "page": page, "limit": limit}


@router.post("/")
async def create_entity(body: EntityCreate, user: dict = Depends(get_current_user)):
    """Create a new entity."""
    entity_data = {
        "name": body.name,
        "entity_type": body.entity_type,
        "address": body.address or "",
        "jurisdiction": body.jurisdiction or "",
        "status": "active",
        "compliance_score": 0,
        "risk_level": "unknown",
        "document_count": 0,
        "organization_id": user.get("org_id", ""),
        "created_by": user["user_id"],
        "metadata": body.metadata or {},
    }
    try:
        entity_id = create_document("entities", entity_data)
        if entity_id:
            return {"entity_id": entity_id, "message": "Entity created", **entity_data}
    except Exception:
        pass

    # Demo fallback
    return {
        "entity_id": "demo-entity-new",
        "message": "Entity created (demo)",
        **entity_data,
    }


@router.get("/benchmark")
async def benchmark_entities(
    entity_ids: Optional[str] = Query(None, description="Comma-separated entity IDs"),
    user: dict = Depends(get_current_user),
):
    """Compare compliance scores across multiple entities."""
    ids = entity_ids.split(",") if entity_ids else []
    results = []

    if ids:
        for eid in ids:
            eid = eid.strip()
            score = calculate_entity_score(eid)
            results.append(score)
    else:
        # Return all entities from demo
        for ent in _demo_entities():
            score = calculate_entity_score(ent["id"])
            score["entity_name"] = ent["name"]
            results.append(score)

    results.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    avg = sum(r.get("overall_score", 0) for r in results) / len(results) if results else 0

    return {
        "entities": results,
        "count": len(results),
        "average_score": round(avg, 1),
        "best": results[0] if results else None,
        "worst": results[-1] if results else None,
    }


@router.get("/{entity_id}")
async def get_entity(entity_id: str, user: dict = Depends(get_current_user)):
    """Get entity details by ID."""
    try:
        entity = get_document("entities", entity_id)
        if entity:
            if user.get("role") != "admin" and entity.get("created_by") != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            return _enrich_entity(entity)
    except HTTPException:
        raise
    except Exception:
        pass

    for e in _demo_entities():
        if e["id"] == entity_id:
            return e
    raise HTTPException(status_code=404, detail="Entity not found")


@router.put("/{entity_id}")
async def update_entity(entity_id: str, body: EntityUpdate, user: dict = Depends(get_current_user)):
    """Update an entity."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Ownership check for non-admin
    if user.get("role") != "admin":
        try:
            entity = get_document("entities", entity_id)
            if entity and entity.get("created_by") != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        success = update_document("entities", entity_id, updates)
        if success:
            return {"message": "Entity updated", "entity_id": entity_id, "updated_fields": list(updates.keys())}
    except Exception:
        pass

    return {"message": "Entity updated (demo)", "entity_id": entity_id, "updated_fields": list(updates.keys())}


@router.delete("/{entity_id}")
async def archive_entity(entity_id: str, user: dict = Depends(get_current_user)):
    """Soft-delete (archive) an entity."""
    # Ownership check for non-admin
    if user.get("role") != "admin":
        try:
            entity = get_document("entities", entity_id)
            if entity and entity.get("created_by") != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        success = update_document("entities", entity_id, {"status": "archived", "archived_by": user["user_id"]})
        if success:
            return {"message": "Entity archived", "entity_id": entity_id}
    except Exception:
        pass

    return {"message": "Entity archived (demo)", "entity_id": entity_id}


@router.get("/{entity_id}/score")
async def get_entity_score(entity_id: str, user: dict = Depends(get_current_user)):
    """Get the compliance score breakdown for an entity."""
    return get_score_breakdown(entity_id)


@router.get("/{entity_id}/documents")
async def get_entity_docs(
    entity_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get all documents belonging to an entity."""
    try:
        docs = get_entity_documents(entity_id)
        if docs:
            total = len(docs)
            start = (page - 1) * limit
            docs = docs[start:start + limit]
            return {"documents": docs, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback - import inline to avoid circular at module level
    from backend.routes.documents import _demo_documents
    demos = [d for d in _demo_documents() if d["entity_id"] == entity_id]
    total = len(demos)
    start = (page - 1) * limit
    demos = demos[start:start + limit]
    return {"documents": demos, "total": total, "page": page, "limit": limit}


@router.get("/{entity_id}/timeline")
async def get_entity_timeline(
    entity_id: str,
    months: int = Query(6, ge=1, le=24),
    user: dict = Depends(get_current_user),
):
    """Get compliance score history timeline for an entity."""
    try:
        history = get_documents(
            "score_history",
            filters=[("entity_id", "==", entity_id)],
            order_by="calculated_at",
            direction="DESCENDING",
            limit=months,
        )
        if history:
            return {"entity_id": entity_id, "timeline": history, "months": months}
    except Exception:
        pass

    # Demo fallback - generate synthetic history
    now = datetime.now(timezone.utc)
    timeline = []
    base_score = 65.0
    for i in range(months, 0, -1):
        month_date = now - timedelta(days=30 * i)
        # Simulate gradual improvement with some variance
        score = min(100, base_score + (months - i) * 3.5 + (hash(str(i)) % 10 - 5))
        timeline.append({
            "date": month_date.strftime("%Y-%m"),
            "score": round(score, 1),
            "grade": _score_to_grade(score),
            "document_count": 3 + (i % 4),
            "events": [],
        })

    return {"entity_id": entity_id, "timeline": timeline, "months": months}


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
