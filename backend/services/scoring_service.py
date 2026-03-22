"""ComplyChip V3 - Compliance Scoring Service"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.services.firestore_service import (
    get_entity_documents,
    get_document,
    get_organization_rules,
    query_documents,
)

# ---------------------------------------------------------------------------
# Configurable scoring weights (sum = 100)
# ---------------------------------------------------------------------------
WEIGHTS = {
    "expiry": 30,
    "completeness": 25,
    "compliance": 25,
    "vendor_risk": 10,
    "regulatory": 10,
}

# Required document types for a fully compliant entity
REQUIRED_DOC_TYPES = [
    "Insurance Policy",
    "Safety Certificate",
    "Environmental Permit",
    "Vendor Agreement",
    "NDA",
    "Business License",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_entity_score(entity_id: str) -> dict:
    """Calculate the overall compliance score for an entity.

    Returns a dict with overall score (0-100), letter grade, risk level,
    and per-category breakdown.
    """
    try:
        docs = get_entity_documents(entity_id)
    except Exception:
        docs = []

    if not docs:
        return _demo_entity_score(entity_id)

    breakdown = _compute_breakdown(docs, entity_id)
    overall = sum(
        breakdown[cat]["score"] * (WEIGHTS[cat] / 100)
        for cat in WEIGHTS
    )
    overall = round(min(max(overall, 0), 100), 1)

    return {
        "entity_id": entity_id,
        "overall_score": overall,
        "grade": _score_to_grade(overall),
        "risk_level": _score_to_risk(overall),
        "breakdown": breakdown,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(docs),
    }


def calculate_document_score(doc: dict) -> dict:
    """Calculate compliance score for a single document.

    Considers expiry status, completeness of metadata, and document type.
    """
    score = 100.0
    penalties = []

    # Expiry check
    expiry_str = doc.get("expiry_date") or doc.get("expiration_date")
    if expiry_str:
        try:
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            else:
                expiry = expiry_str
            now = datetime.now(timezone.utc)
            if expiry < now:
                days_expired = (now - expiry).days
                penalty = min(50, 10 + days_expired)
                score -= penalty
                penalties.append({
                    "category": "expiry",
                    "penalty": penalty,
                    "reason": f"Document expired {days_expired} days ago",
                })
            elif expiry < now + timedelta(days=30):
                score -= 10
                penalties.append({
                    "category": "expiry",
                    "penalty": 10,
                    "reason": "Document expiring within 30 days",
                })
        except (ValueError, TypeError):
            score -= 5
            penalties.append({
                "category": "expiry",
                "penalty": 5,
                "reason": "Could not parse expiry date",
            })
    else:
        score -= 15
        penalties.append({
            "category": "expiry",
            "penalty": 15,
            "reason": "No expiry date set",
        })

    # Metadata completeness
    required_fields = ["document_type", "entity_id", "document_company_name"]
    missing = [f for f in required_fields if not doc.get(f)]
    if missing:
        penalty = len(missing) * 5
        score -= penalty
        penalties.append({
            "category": "completeness",
            "penalty": penalty,
            "reason": f"Missing fields: {', '.join(missing)}",
        })

    # Status check
    status = doc.get("status", "").lower()
    if status == "rejected":
        score -= 25
        penalties.append({
            "category": "compliance",
            "penalty": 25,
            "reason": "Document has been rejected",
        })
    elif status == "pending_review":
        score -= 10
        penalties.append({
            "category": "compliance",
            "penalty": 10,
            "reason": "Document is pending review",
        })

    score = round(max(score, 0), 1)
    return {
        "doc_id": doc.get("id", "unknown"),
        "score": score,
        "grade": _score_to_grade(score),
        "penalties": penalties,
    }


def get_score_breakdown(entity_id: str) -> dict:
    """Get a detailed score breakdown for an entity with per-category details."""
    try:
        docs = get_entity_documents(entity_id)
    except Exception:
        docs = []

    if not docs:
        return _demo_breakdown(entity_id)

    breakdown = _compute_breakdown(docs, entity_id)
    overall = sum(
        breakdown[cat]["score"] * (WEIGHTS[cat] / 100)
        for cat in WEIGHTS
    )
    overall = round(min(max(overall, 0), 100), 1)

    # Per-document scores
    doc_scores = [calculate_document_score(d) for d in docs]

    return {
        "entity_id": entity_id,
        "overall_score": overall,
        "grade": _score_to_grade(overall),
        "risk_level": _score_to_risk(overall),
        "weights": WEIGHTS,
        "breakdown": breakdown,
        "document_scores": doc_scores,
        "recommendations": _generate_recommendations(breakdown),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_breakdown(docs: list, entity_id: str) -> dict:
    """Compute per-category scores."""
    now = datetime.now(timezone.utc)

    # --- Expiry score ---
    expiry_score = 100.0
    expired_count = 0
    expiring_soon = 0
    for doc in docs:
        exp_str = doc.get("expiry_date") or doc.get("expiration_date")
        if exp_str:
            try:
                if isinstance(exp_str, str):
                    exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                else:
                    exp = exp_str
                if exp < now:
                    expired_count += 1
                elif exp < now + timedelta(days=30):
                    expiring_soon += 1
            except (ValueError, TypeError):
                pass

    if docs:
        expiry_score -= (expired_count / len(docs)) * 80
        expiry_score -= (expiring_soon / len(docs)) * 20
    expiry_score = max(expiry_score, 0)

    # --- Completeness score ---
    doc_types_present = {d.get("document_type", "") for d in docs}
    required_present = sum(1 for rt in REQUIRED_DOC_TYPES if rt in doc_types_present)
    completeness_score = (required_present / len(REQUIRED_DOC_TYPES)) * 100

    # --- Compliance score ---
    approved = sum(1 for d in docs if d.get("status", "").lower() == "approved")
    compliance_score = (approved / len(docs)) * 100 if docs else 0

    # --- Vendor risk score (inverse: lower vendor risk -> higher score) ---
    vendor_risk_score = 80.0  # default moderate
    high_risk_vendors = sum(
        1 for d in docs
        if d.get("vendor_risk_level", "").lower() == "high"
    )
    if docs:
        vendor_risk_score = max(0, 100 - (high_risk_vendors / len(docs)) * 100)

    # --- Regulatory score ---
    regulatory_score = 75.0  # baseline
    for doc in docs:
        if doc.get("regulatory_flag"):
            regulatory_score -= 10

    return {
        "expiry": {
            "score": round(expiry_score, 1),
            "weight": WEIGHTS["expiry"],
            "expired_docs": expired_count,
            "expiring_soon": expiring_soon,
        },
        "completeness": {
            "score": round(completeness_score, 1),
            "weight": WEIGHTS["completeness"],
            "required_types": len(REQUIRED_DOC_TYPES),
            "present_types": required_present,
            "missing_types": [rt for rt in REQUIRED_DOC_TYPES if rt not in doc_types_present],
        },
        "compliance": {
            "score": round(compliance_score, 1),
            "weight": WEIGHTS["compliance"],
            "approved_docs": approved,
            "total_docs": len(docs),
        },
        "vendor_risk": {
            "score": round(vendor_risk_score, 1),
            "weight": WEIGHTS["vendor_risk"],
            "high_risk_vendors": high_risk_vendors,
        },
        "regulatory": {
            "score": round(max(regulatory_score, 0), 1),
            "weight": WEIGHTS["regulatory"],
        },
    }


def _generate_recommendations(breakdown: dict) -> list:
    """Generate actionable recommendations based on score breakdown."""
    recs = []
    if breakdown["expiry"]["expired_docs"] > 0:
        recs.append({
            "priority": "critical",
            "category": "expiry",
            "message": f"Renew {breakdown['expiry']['expired_docs']} expired document(s) immediately.",
        })
    if breakdown["expiry"]["expiring_soon"] > 0:
        recs.append({
            "priority": "high",
            "category": "expiry",
            "message": f"{breakdown['expiry']['expiring_soon']} document(s) expiring within 30 days.",
        })
    if breakdown["completeness"]["missing_types"]:
        recs.append({
            "priority": "high",
            "category": "completeness",
            "message": f"Upload missing documents: {', '.join(breakdown['completeness']['missing_types'][:3])}.",
        })
    if breakdown["compliance"]["score"] < 70:
        recs.append({
            "priority": "medium",
            "category": "compliance",
            "message": "Review and approve pending documents to improve compliance score.",
        })
    if breakdown["vendor_risk"]["high_risk_vendors"] > 0:
        recs.append({
            "priority": "medium",
            "category": "vendor_risk",
            "message": f"Assess {breakdown['vendor_risk']['high_risk_vendors']} high-risk vendor(s).",
        })
    return recs


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


def _score_to_risk(score: float) -> str:
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_entity_score(entity_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "overall_score": 73.5,
        "grade": "C",
        "risk_level": "medium",
        "breakdown": _demo_breakdown(entity_id)["breakdown"],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": 8,
    }


def _demo_breakdown(entity_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "overall_score": 73.5,
        "grade": "C",
        "risk_level": "medium",
        "weights": WEIGHTS,
        "breakdown": {
            "expiry": {
                "score": 65.0,
                "weight": 30,
                "expired_docs": 2,
                "expiring_soon": 1,
            },
            "completeness": {
                "score": 83.3,
                "weight": 25,
                "required_types": 6,
                "present_types": 5,
                "missing_types": ["Environmental Permit"],
            },
            "compliance": {
                "score": 75.0,
                "weight": 25,
                "approved_docs": 6,
                "total_docs": 8,
            },
            "vendor_risk": {
                "score": 70.0,
                "weight": 10,
                "high_risk_vendors": 1,
            },
            "regulatory": {
                "score": 75.0,
                "weight": 10,
            },
        },
        "document_scores": [],
        "recommendations": [
            {
                "priority": "critical",
                "category": "expiry",
                "message": "Renew 2 expired document(s) immediately.",
            },
            {
                "priority": "high",
                "category": "completeness",
                "message": "Upload missing documents: Environmental Permit.",
            },
        ],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
