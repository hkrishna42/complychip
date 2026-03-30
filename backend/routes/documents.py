"""ComplyChip V3 - Document Routes"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import (
    get_document,
    get_documents,
    update_document,
    query_documents,
)
from backend.services.gcs_service import generate_signed_url
from backend.services.gemini_service import extract_metadata, analyze_compliance_gaps
from backend.services.scoring_service import calculate_document_score

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_entity_name_cache: dict = {}


def _resolve_entity_name(entity_id: str) -> str:
    """Look up entity name by ID with simple in-memory caching."""
    if not entity_id:
        return ""
    if entity_id in _entity_name_cache:
        return _entity_name_cache[entity_id]
    try:
        ent = get_document("entities", entity_id)
        name = ent.get("name", "") if ent else ""
    except Exception:
        name = ""
    _entity_name_cache[entity_id] = name
    return name


def _score_from_doc(d: dict) -> int:
    """Derive a compliance score for a document."""
    # Use explicit score if present and non-zero
    if d.get("score") is not None and d["score"] != 0:
        return int(d["score"])
    # Documents still being processed get a neutral score
    status = d.get("status", "")
    if status in ("processing", "uploading"):
        return 0
    if status == "expired":
        return 35
    days = d.get("days_remaining")
    if days is not None:
        if days < 0:
            return 30
        if days <= 30:
            return 55
        if days <= 90:
            return 75
        return 90
    if status in ("active", "approved", "compliant", "processed"):
        return 85
    if status == "pending_review":
        return 65
    return 50


def _normalize_date_str(date_str: str) -> str:
    """Normalize various date formats to ISO 8601."""
    import re
    if not date_str:
        return date_str
    date_str = date_str.strip()
    # mm-dd-yyyy or mm/dd/yyyy → yyyy-mm-dd
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", date_str)
    if m:
        month, day, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date_str


def _normalize_doc(d: dict) -> dict:
    """Normalize Firestore document fields to API format.

    Handles both legacy demo data and AI-enriched data from n8n pipeline.
    """
    # Name normalization (n8n may write document_name, Firestore may have title)
    if "title" in d and "name" not in d:
        d["name"] = d.pop("title")
    if "document_name" in d and not d.get("name"):
        d["name"] = d.pop("document_name")

    # Date serialization (Firestore Timestamp → ISO string)
    for key in ("expiry_date", "effective_date", "upload_date", "created_at",
                "updated_at", "processed_at"):
        val = d.get(key)
        if val and hasattr(val, "isoformat"):
            d[key] = val.isoformat()

    # Normalize date formats (mm-dd-yyyy → yyyy-mm-dd)
    for key in ("expiry_date", "effective_date"):
        if d.get(key) and isinstance(d[key], str):
            d[key] = _normalize_date_str(d[key])

    # Compute days_remaining from expiry_date
    if d.get("expiry_date"):
        try:
            exp = d["expiry_date"]
            if isinstance(exp, str):
                # Handle date-only strings
                if len(exp) == 10:
                    exp_dt = datetime.fromisoformat(exp + "T00:00:00+00:00")
                else:
                    exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            else:
                exp_dt = exp
            d["days_remaining"] = (exp_dt - datetime.now(timezone.utc)).days
        except (ValueError, TypeError):
            pass

    # Resolve entity name if missing
    if not d.get("entity_name") and d.get("entity_id"):
        d["entity_name"] = _resolve_entity_name(d["entity_id"])

    # Ensure AI fields default to sensible values
    d.setdefault("ai_summary", None)
    d.setdefault("ai_tags", [])
    d.setdefault("document_company_name", d.get("company_name", ""))
    d.setdefault("compliance_status", "pending")

    # Processing indicator for frontend
    status = d.get("status", "")
    d["is_processing"] = status in ("processing", "uploading")

    # Compute score
    d["score"] = _score_from_doc(d)

    return d


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class DocumentUpdate(BaseModel):
    document_type: Optional[str] = None
    status: Optional[str] = None
    entity_id: Optional[str] = None
    notes: Optional[str] = None
    expiry_date: Optional[str] = None
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_documents() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "doc-001",
            "name": "General Liability Insurance - Sunrise Properties",
            "document_type": "Insurance Policy",
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "status": "approved",
            "expiry_date": (now + timedelta(days=45)).isoformat(),
            "uploaded_at": (now - timedelta(days=200)).isoformat(),
            "file_size": 245000,
            "gcs_path": "entities/entity-001/abc123_insurance.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "SafeGuard Insurance Co.",
            "score": 88,
        },
        {
            "id": "doc-002",
            "name": "OSHA Safety Certificate - Harbor View",
            "document_type": "Safety Certificate",
            "entity_id": "entity-002",
            "entity_name": "Harbor View Complex",
            "status": "approved",
            "expiry_date": (now + timedelta(days=120)).isoformat(),
            "uploaded_at": (now - timedelta(days=90)).isoformat(),
            "file_size": 182000,
            "gcs_path": "entities/entity-002/def456_safety.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "National Safety Council",
            "score": 95,
        },
        {
            "id": "doc-003",
            "name": "EPA Environmental Permit #EP-2025-4421",
            "document_type": "Environmental Permit",
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "status": "pending_review",
            "expiry_date": (now + timedelta(days=300)).isoformat(),
            "uploaded_at": (now - timedelta(days=30)).isoformat(),
            "file_size": 520000,
            "gcs_path": "entities/entity-001/ghi789_envpermit.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "EPA Region 5",
            "score": 72,
        },
        {
            "id": "doc-004",
            "name": "Master Vendor Agreement - EcoClean Services",
            "document_type": "Vendor Agreement",
            "entity_id": "entity-003",
            "entity_name": "Oakmont Residences",
            "status": "approved",
            "expiry_date": (now + timedelta(days=180)).isoformat(),
            "uploaded_at": (now - timedelta(days=150)).isoformat(),
            "file_size": 310000,
            "gcs_path": "entities/entity-003/jkl012_vendor.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "EcoClean Services",
            "score": 91,
        },
        {
            "id": "doc-005",
            "name": "Mutual NDA - TechServe Solutions",
            "document_type": "NDA",
            "entity_id": "entity-002",
            "entity_name": "Harbor View Complex",
            "status": "approved",
            "expiry_date": (now + timedelta(days=365)).isoformat(),
            "uploaded_at": (now - timedelta(days=60)).isoformat(),
            "file_size": 98000,
            "gcs_path": "entities/entity-002/mno345_nda.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "TechServe Solutions",
            "score": 97,
        },
        {
            "id": "doc-006",
            "name": "Employment Contract - J. Martinez",
            "document_type": "Employment Contract",
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "status": "approved",
            "expiry_date": (now + timedelta(days=730)).isoformat(),
            "uploaded_at": (now - timedelta(days=400)).isoformat(),
            "file_size": 175000,
            "gcs_path": "entities/entity-001/pqr678_employment.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "Sunrise Properties LLC",
            "score": 85,
        },
        {
            "id": "doc-007",
            "name": "Business License - Oakmont Residences",
            "document_type": "Business License",
            "entity_id": "entity-003",
            "entity_name": "Oakmont Residences",
            "status": "expired",
            "expiry_date": (now - timedelta(days=15)).isoformat(),
            "uploaded_at": (now - timedelta(days=380)).isoformat(),
            "file_size": 67000,
            "gcs_path": "entities/entity-003/stu901_license.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "City of Oakmont",
            "score": 35,
        },
        {
            "id": "doc-008",
            "name": "Workers Comp Insurance - Harbor View",
            "document_type": "Insurance Policy",
            "entity_id": "entity-002",
            "entity_name": "Harbor View Complex",
            "status": "approved",
            "expiry_date": (now + timedelta(days=90)).isoformat(),
            "uploaded_at": (now - timedelta(days=275)).isoformat(),
            "file_size": 290000,
            "gcs_path": "entities/entity-002/vwx234_workcomp.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "SafeGuard Insurance Co.",
            "score": 82,
        },
        {
            "id": "doc-009",
            "name": "Fire Safety Inspection Report",
            "document_type": "Safety Certificate",
            "entity_id": "entity-003",
            "entity_name": "Oakmont Residences",
            "status": "pending_review",
            "expiry_date": (now + timedelta(days=60)).isoformat(),
            "uploaded_at": (now - timedelta(days=10)).isoformat(),
            "file_size": 430000,
            "gcs_path": "entities/entity-003/yza567_firesafety.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "City Fire Marshal",
            "score": 68,
        },
        {
            "id": "doc-010",
            "name": "Subcontractor Agreement - QuickBuild Contractors",
            "document_type": "Vendor Agreement",
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "status": "rejected",
            "expiry_date": (now + timedelta(days=200)).isoformat(),
            "uploaded_at": (now - timedelta(days=5)).isoformat(),
            "file_size": 355000,
            "gcs_path": "entities/entity-001/bcd890_subcontract.pdf",
            "organization_id": "demo-org-001",
            "document_company_name": "QuickBuild Contractors",
            "score": 42,
        },
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def list_documents(
    entity_id: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None, alias="document_type"),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """List documents with optional filters, pagination, and search."""
    firestore_available = True
    try:
        filters = []
        is_admin = user.get("role") == "admin"
        org_id = user.get("org_id", "")
        # Non-admin users: filter by org and their own uploads
        if not is_admin:
            if org_id:
                filters.append(("organization_id", "==", org_id))
            filters.append(("uploaded_by", "==", user["user_id"]))
        if entity_id:
            filters.append(("entity_id", "==", entity_id))
        if doc_type:
            filters.append(("document_type", "==", doc_type))
        if status:
            filters.append(("status", "==", status))
        docs = get_documents("documents", filters=filters if filters else None, limit=limit * page)
        # Normalize all docs (even if empty list)
        docs = [_normalize_doc(d) for d in docs]
        # Simple text search over name / company name
        if search:
            search_lower = search.lower()
            docs = [
                d for d in docs
                if search_lower in d.get("name", "").lower()
                or search_lower in d.get("document_company_name", "").lower()
                or search_lower in d.get("ai_summary", "").lower()
            ]
        total = len(docs)
        start = (page - 1) * limit
        docs = docs[start:start + limit]
        return {"documents": docs, "total": total, "page": page, "limit": limit}
    except Exception:
        firestore_available = False

    # Demo fallback — only when Firestore is completely unavailable, admin only
    if not firestore_available and user.get("role") == "admin":
        demos = _demo_documents()
        if entity_id:
            demos = [d for d in demos if d["entity_id"] == entity_id]
        if doc_type:
            demos = [d for d in demos if d["document_type"] == doc_type]
        if status:
            demos = [d for d in demos if d["status"] == status]
        if search:
            s = search.lower()
            demos = [d for d in demos if s in d["name"].lower() or s in d.get("document_company_name", "").lower()]
        total = len(demos)
        start = (page - 1) * limit
        demos = demos[start:start + limit]
        return {"documents": demos, "total": total, "page": page, "limit": limit}
    return {"documents": [], "total": 0, "page": page, "limit": limit}


@router.get("/{doc_id}")
async def get_single_document(doc_id: str, user: dict = Depends(get_current_user)):
    """Get a single document by ID."""
    try:
        doc = get_document("documents", doc_id)
        if doc:
            # Non-admin can only access their own documents
            if user.get("role") != "admin" and doc.get("uploaded_by") != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            return _normalize_doc(doc)
    except HTTPException:
        raise
    except Exception:
        pass

    # Demo fallback
    for d in _demo_documents():
        if d["id"] == doc_id:
            return d
    raise HTTPException(status_code=404, detail="Document not found")


@router.put("/{doc_id}")
async def update_doc(doc_id: str, body: DocumentUpdate, user: dict = Depends(get_current_user)):
    """Update document metadata."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Ownership check for non-admin
    if user.get("role") != "admin":
        try:
            doc = get_document("documents", doc_id)
            if doc and doc.get("uploaded_by") != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        success = update_document("documents", doc_id, updates)
        if success:
            return {"message": "Document updated", "doc_id": doc_id, "updated_fields": list(updates.keys())}
    except Exception:
        pass

    # Demo fallback
    return {"message": "Document updated (demo)", "doc_id": doc_id, "updated_fields": list(updates.keys())}


@router.delete("/{doc_id}")
async def archive_document(doc_id: str, user: dict = Depends(get_current_user)):
    """Soft-delete (archive) a document and recalculate entity score."""
    try:
        # Get the doc first to find its entity_id
        doc = get_document("documents", doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        # Ownership check for non-admin
        if user.get("role") != "admin" and doc.get("uploaded_by") != user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        entity_id = doc.get("entity_id", "")

        success = update_document("documents", doc_id, {"status": "archived", "archived_by": user["user_id"]})
        if success:
            # Recalculate entity score excluding archived docs
            if entity_id:
                try:
                    all_docs = query_documents("documents", "entity_id", "==", entity_id)
                    active = [d for d in all_docs if d.get("status") != "archived"]
                    scores = [d.get("score", 0) for d in active if d.get("score") is not None]
                    if scores:
                        avg = round(sum(scores) / len(scores), 1)
                        risk = "low" if avg >= 80 else "medium" if avg >= 60 else "high" if avg >= 40 else "critical"
                    else:
                        avg = 0
                        risk = "unknown"
                    update_document("entities", entity_id, {
                        "compliance_score": avg,
                        "risk_level": risk,
                        "document_count": len(active),
                    })
                except Exception:
                    pass
            return {"message": "Document archived", "doc_id": doc_id}
    except Exception:
        pass

    return {"message": "Document archived (demo)", "doc_id": doc_id}


@router.get("/{doc_id}/signed-url")
async def get_signed_url(doc_id: str, user: dict = Depends(get_current_user)):
    """Get a signed download URL for a document."""
    gcs_path = None
    try:
        doc = get_document("documents", doc_id)
        if doc:
            gcs_path = doc.get("gcs_path", "")
    except Exception:
        pass

    if not gcs_path:
        # Try demo
        for d in _demo_documents():
            if d["id"] == doc_id:
                gcs_path = d.get("gcs_path", "")
                break

    if not gcs_path:
        raise HTTPException(status_code=404, detail="Document not found")

    url = generate_signed_url(gcs_path)
    return {"doc_id": doc_id, "signed_url": url, "expires_in": 3600}


@router.get("/{doc_id}/related")
async def get_related_documents(doc_id: str, user: dict = Depends(get_current_user)):
    """Get documents related to the given document (same entity or vendor)."""
    doc = None
    try:
        doc = get_document("documents", doc_id)
    except Exception:
        pass

    if not doc:
        for d in _demo_documents():
            if d["id"] == doc_id:
                doc = d
                break
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    entity_id = doc.get("entity_id", "")
    related = []
    try:
        if entity_id:
            results = query_documents("documents", "entity_id", "==", entity_id)
            related = [r for r in results if r.get("id") != doc_id]
    except Exception:
        pass

    if not related:
        related = [d for d in _demo_documents() if d["entity_id"] == entity_id and d["id"] != doc_id]

    return {"doc_id": doc_id, "related": related[:10], "total": len(related)}


@router.post("/{doc_id}/analyze")
async def analyze_document(doc_id: str, user: dict = Depends(get_current_user)):
    """Trigger AI analysis on a document (metadata extraction + scoring)."""
    doc = None
    try:
        doc = get_document("documents", doc_id)
    except Exception:
        pass

    if not doc:
        for d in _demo_documents():
            if d["id"] == doc_id:
                doc = d
                break
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Extract metadata
    text = doc.get("extracted_text", "Sample compliance document text for analysis.")
    doc_type = doc.get("document_type", "unknown")
    metadata = extract_metadata(text, doc_type)

    # Score the document
    score_result = calculate_document_score(doc)

    # Gap analysis against compliance rules
    rules = [
        {"id": "REG-001", "name": "Insurance Certificate Validity", "description": "Valid general liability and professional indemnity insurance certificates required", "severity": "critical"},
        {"id": "REG-002", "name": "Contract Expiration", "description": "Contract must not be expired and renewal tracking must be in place", "severity": "high"},
        {"id": "REG-003", "name": "Data Processing Agreement", "description": "GDPR-compliant DPA required for all vendors processing personal data", "severity": "high"},
        {"id": "REG-004", "name": "Liability Limitations", "description": "Mutual liability limitations meeting minimum coverage thresholds required", "severity": "medium"},
        {"id": "REG-005", "name": "Termination Provisions", "description": "Clear termination terms with notice periods, data handling, and transition support", "severity": "medium"},
        {"id": "REG-006", "name": "Confidentiality & NDA", "description": "Mutual confidentiality obligations with survival clauses post-termination", "severity": "medium"},
        {"id": "REG-007", "name": "Force Majeure", "description": "Force majeure provisions addressing business continuity and SLA commitments", "severity": "medium"},
        {"id": "REG-008", "name": "Intellectual Property Rights", "description": "Clear IP ownership assignment or licensing for deliverables and pre-existing materials", "severity": "medium"},
        {"id": "REG-009", "name": "Compliance Reporting", "description": "Periodic compliance reporting and certification obligations for regulated activities", "severity": "low"},
        {"id": "REG-010", "name": "Audit Rights", "description": "Contractual right to audit vendor operations, security controls, and subcontractors", "severity": "low"},
        {"id": "REG-011", "name": "Indemnification", "description": "Mutual indemnification for third-party claims arising from breach of obligations", "severity": "medium"},
    ]
    analysis = analyze_compliance_gaps(doc, rules)

    # Persist analysis to Firestore
    try:
        update_document("documents", doc_id, {"compliance_gaps": analysis.get("compliance_gaps", []), "gap_analysis": analysis})
    except Exception:
        pass

    return {
        "doc_id": doc_id,
        "extracted_metadata": metadata,
        "score": score_result,
        "analysis": analysis,
        "analysis_status": "complete",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
