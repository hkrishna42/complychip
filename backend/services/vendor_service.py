"""ComplyChip V3 - Vendor Risk Service"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.services.firestore_service import (
    get_documents,
    get_document,
    get_vendor_documents,
    query_documents,
)

RISK_THRESHOLDS = {
    "low": 30,
    "medium": 60,
    "high": 80,
    "critical": 100,
}


def calculate_vendor_risk(vendor_id: str) -> dict:
    """Calculate a vendor's risk score based on their documents and profile.

    Returns a dict with risk_score (0-100), risk_level, and contributing factors.
    """
    try:
        vendor = get_document("vendors", vendor_id)
    except Exception:
        vendor = None

    if not vendor:
        return _demo_vendor_risk(vendor_id)

    org_id = vendor.get("organization_id", "")
    vendor_name = vendor.get("name", "")

    try:
        docs = get_vendor_documents(vendor_name, org_id)
    except Exception:
        docs = []

    risk_score = 0.0
    factors = []

    # Factor 1: Document completeness
    required_types = {"Insurance Policy", "NDA", "Vendor Agreement"}
    present_types = {d.get("document_type", "") for d in docs}
    missing = required_types - present_types
    if missing:
        penalty = len(missing) * 15
        risk_score += penalty
        factors.append({
            "factor": "missing_documents",
            "impact": penalty,
            "details": f"Missing: {', '.join(missing)}",
        })

    # Factor 2: Expired documents
    now = datetime.now(timezone.utc)
    expired_count = 0
    for doc in docs:
        exp = doc.get("expiry_date") or doc.get("expiration_date")
        if exp:
            try:
                if isinstance(exp, str):
                    exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                else:
                    exp_dt = exp
                if exp_dt < now:
                    expired_count += 1
            except (ValueError, TypeError):
                pass

    if expired_count > 0:
        penalty = min(expired_count * 12, 36)
        risk_score += penalty
        factors.append({
            "factor": "expired_documents",
            "impact": penalty,
            "details": f"{expired_count} expired document(s)",
        })

    # Factor 3: Vendor tier / category
    tier = vendor.get("tier", "").lower()
    if tier == "critical":
        risk_score += 10
        factors.append({
            "factor": "critical_tier",
            "impact": 10,
            "details": "Vendor is classified as a critical-tier supplier",
        })

    # Factor 4: Years of relationship
    onboarded = vendor.get("onboarded_date")
    if onboarded:
        try:
            if isinstance(onboarded, str):
                onb_dt = datetime.fromisoformat(onboarded.replace("Z", "+00:00"))
            else:
                onb_dt = onboarded
            years = (now - onb_dt).days / 365.25
            if years < 1:
                risk_score += 10
                factors.append({
                    "factor": "new_vendor",
                    "impact": 10,
                    "details": f"Vendor onboarded {int(years * 12)} months ago",
                })
        except (ValueError, TypeError):
            pass

    risk_score = min(risk_score, 100)
    risk_level = _score_to_level(risk_score)

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "risk_score": round(risk_score, 1),
        "risk_level": risk_level,
        "factors": factors,
        "document_count": len(docs),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_vendor_summary(organization_id: str) -> dict:
    """Get aggregated vendor risk summary for an organization.

    Returns counts by risk level and overall statistics.
    """
    try:
        vendors = get_documents(
            "vendors",
            filters=[("organization_id", "==", organization_id)],
            limit=100,
        )
    except Exception:
        vendors = []

    if not vendors:
        return _demo_vendor_summary()

    risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    total_risk = 0.0
    vendor_risks = []

    for v in vendors:
        risk_data = calculate_vendor_risk(v.get("id", ""))
        level = risk_data["risk_level"]
        risk_distribution[level] = risk_distribution.get(level, 0) + 1
        total_risk += risk_data["risk_score"]
        vendor_risks.append({
            "vendor_id": v.get("id", ""),
            "vendor_name": v.get("name", ""),
            "risk_score": risk_data["risk_score"],
            "risk_level": risk_data["risk_level"],
        })

    vendor_risks.sort(key=lambda x: x["risk_score"], reverse=True)

    return {
        "organization_id": organization_id,
        "total_vendors": len(vendors),
        "avg_risk_score": round(total_risk / len(vendors), 1) if vendors else 0,
        "risk_distribution": risk_distribution,
        "top_risk_vendors": vendor_risks[:5],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_level(score: float) -> str:
    if score < RISK_THRESHOLDS["low"]:
        return "low"
    if score < RISK_THRESHOLDS["medium"]:
        return "medium"
    if score < RISK_THRESHOLDS["high"]:
        return "high"
    return "critical"


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_vendor_risk(vendor_id: str) -> dict:
    return {
        "vendor_id": vendor_id,
        "vendor_name": "Demo Vendor",
        "risk_score": 42.0,
        "risk_level": "medium",
        "factors": [
            {"factor": "missing_documents", "impact": 15, "details": "Missing: NDA"},
            {"factor": "expired_documents", "impact": 12, "details": "1 expired document(s)"},
            {"factor": "new_vendor", "impact": 10, "details": "Vendor onboarded 6 months ago"},
        ],
        "document_count": 3,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def _demo_vendor_summary() -> dict:
    return {
        "organization_id": "demo-org-001",
        "total_vendors": 6,
        "avg_risk_score": 38.5,
        "risk_distribution": {"low": 2, "medium": 2, "high": 1, "critical": 1},
        "top_risk_vendors": [
            {"vendor_id": "vendor-006", "vendor_name": "QuickBuild Contractors", "risk_score": 82.0, "risk_level": "critical"},
            {"vendor_id": "vendor-005", "vendor_name": "TechServe Solutions", "risk_score": 65.0, "risk_level": "high"},
            {"vendor_id": "vendor-003", "vendor_name": "Metro Waste Management", "risk_score": 45.0, "risk_level": "medium"},
            {"vendor_id": "vendor-004", "vendor_name": "PrimeSec Security", "risk_score": 32.0, "risk_level": "medium"},
            {"vendor_id": "vendor-001", "vendor_name": "SafeGuard Insurance Co.", "risk_score": 18.0, "risk_level": "low"},
        ],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
