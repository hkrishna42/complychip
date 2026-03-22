"""ComplyChip V3 - Vendor Routes"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import (
    get_documents,
    get_document,
    create_document,
    update_document,
    get_vendor_documents,
)
from backend.services.vendor_service import calculate_vendor_risk

router = APIRouter()


def _enrich_vendor(v: dict) -> dict:
    """Add computed fields (risk_level, document_count) if missing."""
    score = v.get("risk_score", 0)
    if not v.get("risk_level"):
        if score < 30:
            v["risk_level"] = "low"
        elif score < 60:
            v["risk_level"] = "medium"
        elif score < 80:
            v["risk_level"] = "high"
        else:
            v["risk_level"] = "critical"
    if v.get("document_count") is None:
        # Count documents associated with this vendor by name
        try:
            from backend.services.firestore_service import get_vendor_documents
            docs = get_vendor_documents(v.get("name", ""), v.get("organization_id", ""))
            v["document_count"] = len(docs)
        except Exception:
            v["document_count"] = 0
    return v


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class VendorCreate(BaseModel):
    name: str
    category: str = "general"
    tier: str = "standard"
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    metadata: Optional[dict] = None


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    tier: Optional[str] = None
    status: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_vendors() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "vendor-001",
            "name": "SafeGuard Insurance Co.",
            "category": "insurance",
            "tier": "critical",
            "status": "active",
            "contact_email": "renewals@safeguardins.com",
            "contact_phone": "+1-555-0101",
            "address": "200 Insurance Blvd, Hartford, CT 06103",
            "risk_score": 18.0,
            "risk_level": "low",
            "document_count": 4,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=900)).isoformat(),
            "created_at": (now - timedelta(days=900)).isoformat(),
        },
        {
            "id": "vendor-002",
            "name": "EcoClean Services",
            "category": "maintenance",
            "tier": "standard",
            "status": "active",
            "contact_email": "contracts@ecoclean.com",
            "contact_phone": "+1-555-0202",
            "address": "45 Green Way, Portland, OR 97201",
            "risk_score": 25.0,
            "risk_level": "low",
            "document_count": 3,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=600)).isoformat(),
            "created_at": (now - timedelta(days=600)).isoformat(),
        },
        {
            "id": "vendor-003",
            "name": "Metro Waste Management",
            "category": "waste",
            "tier": "standard",
            "status": "active",
            "contact_email": "billing@metrowaste.com",
            "contact_phone": "+1-555-0303",
            "address": "1100 Industrial Pkwy, Chicago, IL 60607",
            "risk_score": 45.0,
            "risk_level": "medium",
            "document_count": 2,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=450)).isoformat(),
            "created_at": (now - timedelta(days=450)).isoformat(),
        },
        {
            "id": "vendor-004",
            "name": "PrimeSec Security",
            "category": "security",
            "tier": "standard",
            "status": "active",
            "contact_email": "accounts@primesec.com",
            "contact_phone": "+1-555-0404",
            "address": "88 Shield St, Dallas, TX 75201",
            "risk_score": 32.0,
            "risk_level": "medium",
            "document_count": 3,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=300)).isoformat(),
            "created_at": (now - timedelta(days=300)).isoformat(),
        },
        {
            "id": "vendor-005",
            "name": "TechServe Solutions",
            "category": "technology",
            "tier": "critical",
            "status": "active",
            "contact_email": "support@techserve.io",
            "contact_phone": "+1-555-0505",
            "address": "500 Tech Park, San Jose, CA 95112",
            "risk_score": 65.0,
            "risk_level": "high",
            "document_count": 2,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=120)).isoformat(),
            "created_at": (now - timedelta(days=120)).isoformat(),
        },
        {
            "id": "vendor-006",
            "name": "QuickBuild Contractors",
            "category": "construction",
            "tier": "critical",
            "status": "under_review",
            "contact_email": "projects@quickbuild.com",
            "contact_phone": "+1-555-0606",
            "address": "750 Builder Rd, Phoenix, AZ 85004",
            "risk_score": 82.0,
            "risk_level": "critical",
            "document_count": 1,
            "organization_id": "demo-org-001",
            "onboarded_date": (now - timedelta(days=60)).isoformat(),
            "created_at": (now - timedelta(days=60)).isoformat(),
        },
    ]


def _demo_risk_history(vendor_id: str) -> list:
    now = datetime.now(timezone.utc)
    base = 50.0
    history = []
    for i in range(6, 0, -1):
        d = now - timedelta(days=30 * i)
        score = max(10, base + (hash(str(vendor_id) + str(i)) % 30) - 15)
        history.append({
            "date": d.strftime("%Y-%m"),
            "risk_score": round(score, 1),
            "risk_level": "low" if score < 30 else "medium" if score < 60 else "high" if score < 80 else "critical",
            "document_count": 2 + (i % 3),
        })
    return history


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_vendors(
    category: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """List vendors with optional filters."""
    try:
        filters = []
        org_id = user.get("org_id", "")
        if org_id:
            filters.append(("organization_id", "==", org_id))
        if category:
            filters.append(("category", "==", category))
        if tier:
            filters.append(("tier", "==", tier))
        if status:
            filters.append(("status", "==", status))
        vendors = get_documents("vendors", filters=filters if filters else None, limit=limit * page)
        if vendors:
            vendors = [_enrich_vendor(v) for v in vendors]
            if search:
                s = search.lower()
                vendors = [v for v in vendors if s in v.get("name", "").lower()]
            total = len(vendors)
            start = (page - 1) * limit
            vendors = vendors[start:start + limit]
            return {"vendors": vendors, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback
    demos = _demo_vendors()
    if category:
        demos = [v for v in demos if v["category"] == category]
    if tier:
        demos = [v for v in demos if v["tier"] == tier]
    if status:
        demos = [v for v in demos if v["status"] == status]
    if search:
        s = search.lower()
        demos = [v for v in demos if s in v["name"].lower()]
    total = len(demos)
    start = (page - 1) * limit
    demos = demos[start:start + limit]
    return {"vendors": demos, "total": total, "page": page, "limit": limit}


@router.post("/")
async def create_vendor(body: VendorCreate, user: dict = Depends(get_current_user)):
    """Create a new vendor."""
    vendor_data = {
        "name": body.name,
        "category": body.category,
        "tier": body.tier,
        "status": "active",
        "contact_email": body.contact_email or "",
        "contact_phone": body.contact_phone or "",
        "address": body.address or "",
        "risk_score": 0,
        "risk_level": "unknown",
        "document_count": 0,
        "organization_id": user.get("org_id", ""),
        "created_by": user["user_id"],
        "onboarded_date": datetime.now(timezone.utc).isoformat(),
        "metadata": body.metadata or {},
    }
    try:
        vendor_id = create_document("vendors", vendor_data)
        if vendor_id:
            return {"vendor_id": vendor_id, "message": "Vendor created", **vendor_data}
    except Exception:
        pass

    return {"vendor_id": "demo-vendor-new", "message": "Vendor created (demo)", **vendor_data}


@router.get("/{vendor_id}")
async def get_vendor(vendor_id: str, user: dict = Depends(get_current_user)):
    """Get vendor details by ID."""
    try:
        vendor = get_document("vendors", vendor_id)
        if vendor:
            # Enrich with risk calculation
            risk = calculate_vendor_risk(vendor_id)
            vendor["risk_score"] = risk["risk_score"]
            vendor["risk_level"] = risk["risk_level"]
            vendor["risk_factors"] = risk.get("factors", [])
            return vendor
    except Exception:
        pass

    for v in _demo_vendors():
        if v["id"] == vendor_id:
            return v
    raise HTTPException(status_code=404, detail="Vendor not found")


@router.put("/{vendor_id}")
async def update_vendor(vendor_id: str, body: VendorUpdate, user: dict = Depends(get_current_user)):
    """Update vendor information."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        success = update_document("vendors", vendor_id, updates)
        if success:
            return {"message": "Vendor updated", "vendor_id": vendor_id, "updated_fields": list(updates.keys())}
    except Exception:
        pass

    return {"message": "Vendor updated (demo)", "vendor_id": vendor_id, "updated_fields": list(updates.keys())}


@router.get("/{vendor_id}/documents")
async def get_vendor_docs(
    vendor_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get all documents associated with a vendor."""
    vendor = None
    try:
        vendor = get_document("vendors", vendor_id)
    except Exception:
        pass

    if not vendor:
        for v in _demo_vendors():
            if v["id"] == vendor_id:
                vendor = v
                break

    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor_name = vendor.get("name", "")
    org_id = vendor.get("organization_id", "")

    try:
        docs = get_vendor_documents(vendor_name, org_id)
        if docs:
            total = len(docs)
            start = (page - 1) * limit
            docs = docs[start:start + limit]
            return {"vendor_id": vendor_id, "documents": docs, "total": total, "page": page, "limit": limit}
    except Exception:
        pass

    # Demo fallback
    from backend.routes.documents import _demo_documents
    demos = [d for d in _demo_documents() if d.get("document_company_name", "") == vendor_name]
    total = len(demos)
    start = (page - 1) * limit
    demos = demos[start:start + limit]
    return {"vendor_id": vendor_id, "documents": demos, "total": total, "page": page, "limit": limit}


@router.get("/{vendor_id}/risk-history")
async def get_risk_history(
    vendor_id: str,
    months: int = Query(6, ge=1, le=24),
    user: dict = Depends(get_current_user),
):
    """Get vendor risk score history."""
    try:
        history = get_documents(
            "vendor_risk_history",
            filters=[("vendor_id", "==", vendor_id)],
            order_by="date",
            direction="DESCENDING",
            limit=months,
        )
        if history:
            return {"vendor_id": vendor_id, "history": history, "months": months}
    except Exception:
        pass

    return {"vendor_id": vendor_id, "history": _demo_risk_history(vendor_id), "months": months}
