"""ComplyChip V3 - Compliance Routes"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_current_user, require_roles
from backend.services.firestore_service import (
    get_documents,
    get_document,
    create_document,
    update_document,
)
from backend.services.scoring_service import (
    calculate_entity_score,
    get_score_breakdown,
)
from backend.services.gemini_service import analyze_compliance_gaps

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RuleCreate(BaseModel):
    name: str
    description: str
    category: str = "general"
    severity: str = "medium"
    document_types: Optional[list] = None
    requirement: Optional[str] = None
    is_active: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    document_types: Optional[list] = None
    requirement: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_scores() -> list:
    return [
        {"entity_id": "entity-001", "entity_name": "Sunrise Properties LLC", "overall_score": 73.5, "grade": "C", "risk_level": "medium", "document_count": 5},
        {"entity_id": "entity-002", "entity_name": "Harbor View Complex", "overall_score": 88.2, "grade": "B", "risk_level": "low", "document_count": 4},
        {"entity_id": "entity-003", "entity_name": "Oakmont Residences", "overall_score": 56.0, "grade": "F", "risk_level": "high", "document_count": 3},
        {"entity_id": "entity-004", "entity_name": "Riverside Tower", "overall_score": 92.1, "grade": "A", "risk_level": "low", "document_count": 6},
        {"entity_id": "entity-005", "entity_name": "Metro Heights", "overall_score": 41.0, "grade": "F", "risk_level": "critical", "document_count": 2},
    ]


def _demo_rules() -> list:
    return [
        {
            "id": "rule-001",
            "name": "Insurance Certificate Validity",
            "description": "All entities must maintain valid, non-expired general liability insurance certificates.",
            "category": "insurance",
            "severity": "critical",
            "document_types": ["Insurance Policy"],
            "requirement": "Certificate must have a future expiry date",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-002",
            "name": "Safety Inspection Currency",
            "description": "Safety inspection certificates must be renewed annually.",
            "category": "safety",
            "severity": "high",
            "document_types": ["Safety Certificate"],
            "requirement": "Inspection date within last 12 months",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-003",
            "name": "Vendor Agreement On File",
            "description": "All active vendors must have a signed vendor agreement or master service agreement.",
            "category": "vendor",
            "severity": "high",
            "document_types": ["Vendor Agreement"],
            "requirement": "Signed agreement for each active vendor",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-004",
            "name": "NDA Execution",
            "description": "Non-disclosure agreements required for vendors with access to proprietary data.",
            "category": "confidentiality",
            "severity": "medium",
            "document_types": ["NDA"],
            "requirement": "Executed NDA on file",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-005",
            "name": "Environmental Permit Compliance",
            "description": "Properties must maintain current environmental permits as required by jurisdiction.",
            "category": "environmental",
            "severity": "high",
            "document_types": ["Environmental Permit"],
            "requirement": "Valid permit matching property jurisdiction",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-006",
            "name": "Business License Active",
            "description": "Each entity must have a current, active business license.",
            "category": "licensing",
            "severity": "critical",
            "document_types": ["Business License"],
            "requirement": "Non-expired business license on file",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-007",
            "name": "Employment Contract Completeness",
            "description": "All employees must have signed employment contracts with required clauses.",
            "category": "employment",
            "severity": "medium",
            "document_types": ["Employment Contract"],
            "requirement": "Signed contract with compensation, termination, and confidentiality clauses",
            "is_active": True,
            "organization_id": "demo-org-001",
        },
        {
            "id": "rule-008",
            "name": "Data Processing Agreement",
            "description": "Vendors handling PII must have a signed Data Processing Agreement.",
            "category": "privacy",
            "severity": "high",
            "document_types": ["Vendor Agreement", "NDA"],
            "requirement": "DPA executed with data-handling vendors",
            "is_active": False,
            "organization_id": "demo-org-001",
        },
    ]


def _demo_gaps() -> list:
    return [
        {
            "entity_id": "entity-003",
            "entity_name": "Oakmont Residences",
            "rule_id": "rule-006",
            "rule_name": "Business License Active",
            "severity": "critical",
            "description": "Business license expired 15 days ago.",
            "recommendation": "Renew business license with the City of Oakmont immediately.",
        },
        {
            "entity_id": "entity-005",
            "entity_name": "Metro Heights",
            "rule_id": "rule-001",
            "rule_name": "Insurance Certificate Validity",
            "severity": "critical",
            "description": "General liability insurance has lapsed.",
            "recommendation": "Obtain new insurance certificate from carrier.",
        },
        {
            "entity_id": "entity-005",
            "entity_name": "Metro Heights",
            "rule_id": "rule-002",
            "rule_name": "Safety Inspection Currency",
            "severity": "high",
            "description": "No safety inspection on record within the past 12 months.",
            "recommendation": "Schedule safety inspection with certified inspector.",
        },
        {
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "rule_id": "rule-001",
            "rule_name": "Insurance Certificate Validity",
            "severity": "high",
            "description": "Insurance policy expiring within 30 days.",
            "recommendation": "Initiate renewal process with SafeGuard Insurance.",
        },
        {
            "entity_id": "entity-001",
            "entity_name": "Sunrise Properties LLC",
            "rule_id": "rule-005",
            "rule_name": "Environmental Permit Compliance",
            "severity": "medium",
            "description": "Environmental permit is pending review.",
            "recommendation": "Follow up with EPA Region 5 for permit approval.",
        },
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/scores")
async def get_all_scores(user: dict = Depends(get_current_user)):
    """Get compliance scores for all entities."""
    try:
        org_id = user.get("org_id", "")
        filters = [("organization_id", "==", org_id)] if org_id else None
        entities = get_documents("entities", filters=filters, limit=100)
        if entities:
            scores = []
            for ent in entities:
                score = calculate_entity_score(ent.get("id", ""))
                score["entity_name"] = ent.get("name", "")
                scores.append(score)
            scores.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
            return {"scores": scores, "count": len(scores)}
    except Exception:
        pass

    return {"scores": _demo_scores(), "count": len(_demo_scores())}


@router.get("/scores/{entity_id}")
async def get_entity_score(entity_id: str, user: dict = Depends(get_current_user)):
    """Get compliance score for a specific entity."""
    return get_score_breakdown(entity_id)


@router.post("/recalculate/{entity_id}")
async def recalculate_score(entity_id: str, user: dict = Depends(get_current_user)):
    """Force recalculate the compliance score for an entity."""
    score = calculate_entity_score(entity_id)

    # Persist the new score
    try:
        update_document("entities", entity_id, {
            "compliance_score": score["overall_score"],
            "risk_level": score["risk_level"],
        })
        # Store in history
        create_document("score_history", {
            "entity_id": entity_id,
            "score": score["overall_score"],
            "grade": score["grade"],
            "risk_level": score["risk_level"],
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return {
        "message": "Score recalculated",
        "entity_id": entity_id,
        **score,
    }


@router.get("/gaps")
async def get_all_gaps(
    severity: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Get all compliance gaps across the organization."""
    try:
        org_id = user.get("org_id", "")
        filters = [("organization_id", "==", org_id)] if org_id else None
        if severity:
            filters = filters or []
            filters.append(("severity", "==", severity))
        gaps = get_documents("compliance_gaps", filters=filters, limit=100)
        if gaps:
            return {"gaps": gaps, "count": len(gaps)}
    except Exception:
        pass

    demos = _demo_gaps()
    if severity:
        demos = [g for g in demos if g["severity"] == severity]
    return {"gaps": demos, "count": len(demos)}


@router.get("/gaps/{entity_id}")
async def get_entity_gaps(entity_id: str, user: dict = Depends(get_current_user)):
    """Get compliance gaps for a specific entity."""
    try:
        gaps = get_documents(
            "compliance_gaps",
            filters=[("entity_id", "==", entity_id)],
            limit=50,
        )
        if gaps:
            return {"entity_id": entity_id, "gaps": gaps, "count": len(gaps)}
    except Exception:
        pass

    demos = [g for g in _demo_gaps() if g["entity_id"] == entity_id]
    return {"entity_id": entity_id, "gaps": demos, "count": len(demos)}


@router.get("/rules")
async def list_rules(
    category: Optional[str] = Query(None),
    active_only: bool = Query(True),
    user: dict = Depends(get_current_user),
):
    """List compliance rules."""
    try:
        org_id = user.get("org_id", "")
        filters = []
        if org_id:
            filters.append(("organization_id", "==", org_id))
        if active_only:
            filters.append(("is_active", "==", True))
        rules = get_documents("compliance_rules", filters=filters if filters else None, limit=100)
        if rules:
            if category:
                rules = [r for r in rules if r.get("category") == category]
            return {"rules": rules, "count": len(rules)}
    except Exception:
        pass

    demos = _demo_rules()
    if active_only:
        demos = [r for r in demos if r.get("is_active", True)]
    if category:
        demos = [r for r in demos if r["category"] == category]
    return {"rules": demos, "count": len(demos)}


@router.post("/rules")
async def create_rule(
    body: RuleCreate,
    user: dict = Depends(require_roles("admin")),
):
    """Create a new compliance rule (admin only)."""
    rule_data = {
        "name": body.name,
        "description": body.description,
        "category": body.category,
        "severity": body.severity,
        "document_types": body.document_types or [],
        "requirement": body.requirement or "",
        "is_active": body.is_active,
        "organization_id": user.get("org_id", ""),
        "created_by": user["user_id"],
    }
    try:
        rule_id = create_document("compliance_rules", rule_data)
        if rule_id:
            return {"rule_id": rule_id, "message": "Rule created", **rule_data}
    except Exception:
        pass

    return {"rule_id": "demo-rule-new", "message": "Rule created (demo)", **rule_data}


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    user: dict = Depends(require_roles("admin")),
):
    """Update a compliance rule (admin only)."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        success = update_document("compliance_rules", rule_id, updates)
        if success:
            return {"message": "Rule updated", "rule_id": rule_id, "updated_fields": list(updates.keys())}
    except Exception:
        pass

    return {"message": "Rule updated (demo)", "rule_id": rule_id, "updated_fields": list(updates.keys())}
