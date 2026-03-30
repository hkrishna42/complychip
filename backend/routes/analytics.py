"""ComplyChip V3 - Analytics Routes"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.dependencies import get_current_user
from backend.services.firestore_service import get_documents
from backend.services.scoring_service import calculate_entity_score
from backend.services.vendor_service import get_vendor_summary

router = APIRouter()


# ---------------------------------------------------------------------------
# Demo data generators
# ---------------------------------------------------------------------------

def _demo_summary() -> dict:
    return {
        "total_documents": 47,
        "total_entities": 5,
        "total_vendors": 6,
        "expiring_30d": 4,
        "expiring_60d": 7,
        "expiring_90d": 12,
        "expired": 3,
        "avg_compliance_score": 72.4,
        "risk_distribution": {
            "low": 2,
            "medium": 1,
            "high": 1,
            "critical": 1,
        },
        "status_distribution": {
            "approved": 32,
            "pending_review": 8,
            "expired": 3,
            "rejected": 2,
            "archived": 2,
        },
        "document_type_distribution": {
            "Insurance Policy": 10,
            "Safety Certificate": 8,
            "Vendor Agreement": 7,
            "NDA": 6,
            "Environmental Permit": 5,
            "Employment Contract": 5,
            "Business License": 4,
            "Other": 2,
        },
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def _demo_trends(months: int) -> list:
    now = datetime.now(timezone.utc)
    trends = []
    base = 62.0
    for i in range(months, 0, -1):
        d = now - timedelta(days=30 * i)
        score = min(95, base + (months - i) * 2.8 + (hash(str(i + 42)) % 8 - 3))
        trends.append({
            "date": d.strftime("%Y-%m"),
            "avg_score": round(score, 1),
            "total_docs": 30 + i * 2,
            "approved_docs": 20 + i,
            "expired_docs": max(0, 5 - (months - i)),
            "new_uploads": 3 + (hash(str(i)) % 5),
        })
    return trends


def _demo_risk_matrix() -> list:
    return [
        {"entity_id": "entity-001", "entity_name": "Sunrise Properties LLC", "score": 73.5, "risk_level": "medium", "document_count": 5, "expired_count": 1},
        {"entity_id": "entity-002", "entity_name": "Harbor View Complex", "score": 88.2, "risk_level": "low", "document_count": 4, "expired_count": 0},
        {"entity_id": "entity-003", "entity_name": "Oakmont Residences", "score": 56.0, "risk_level": "high", "document_count": 3, "expired_count": 2},
        {"entity_id": "entity-004", "entity_name": "Riverside Tower", "score": 92.1, "risk_level": "low", "document_count": 6, "expired_count": 0},
        {"entity_id": "entity-005", "entity_name": "Metro Heights", "score": 41.0, "risk_level": "critical", "document_count": 2, "expired_count": 2},
    ]


def _demo_expiry_forecast() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "buckets": {
            "overdue": [
                {"doc_id": "doc-007", "name": "Business License - Oakmont Residences", "entity_name": "Oakmont Residences", "expiry_date": (now - timedelta(days=15)).isoformat(), "document_type": "Business License", "days_overdue": 15},
                {"doc_id": "doc-011", "name": "Safety Inspection - Metro Heights", "entity_name": "Metro Heights", "expiry_date": (now - timedelta(days=45)).isoformat(), "document_type": "Safety Certificate", "days_overdue": 45},
                {"doc_id": "doc-012", "name": "Environmental Permit - Metro Heights", "entity_name": "Metro Heights", "expiry_date": (now - timedelta(days=30)).isoformat(), "document_type": "Environmental Permit", "days_overdue": 30},
            ],
            "next_30_days": [
                {"doc_id": "doc-001", "name": "General Liability Insurance - Sunrise Properties", "entity_name": "Sunrise Properties LLC", "expiry_date": (now + timedelta(days=20)).isoformat(), "document_type": "Insurance Policy", "days_until_expiry": 20},
                {"doc_id": "doc-013", "name": "Vendor Agreement - PrimeSec", "entity_name": "Harbor View Complex", "expiry_date": (now + timedelta(days=28)).isoformat(), "document_type": "Vendor Agreement", "days_until_expiry": 28},
            ],
            "next_60_days": [
                {"doc_id": "doc-009", "name": "Fire Safety Inspection Report", "entity_name": "Oakmont Residences", "expiry_date": (now + timedelta(days=55)).isoformat(), "document_type": "Safety Certificate", "days_until_expiry": 55},
                {"doc_id": "doc-008", "name": "Workers Comp Insurance - Harbor View", "entity_name": "Harbor View Complex", "expiry_date": (now + timedelta(days=48)).isoformat(), "document_type": "Insurance Policy", "days_until_expiry": 48},
            ],
            "next_90_days": [
                {"doc_id": "doc-014", "name": "NDA - Metro Waste", "entity_name": "Sunrise Properties LLC", "expiry_date": (now + timedelta(days=75)).isoformat(), "document_type": "NDA", "days_until_expiry": 75},
                {"doc_id": "doc-015", "name": "Employment Contract - A. Lee", "entity_name": "Riverside Tower", "expiry_date": (now + timedelta(days=82)).isoformat(), "document_type": "Employment Contract", "days_until_expiry": 82},
            ],
        },
        "summary": {
            "overdue_count": 3,
            "next_30_count": 2,
            "next_60_count": 2,
            "next_90_count": 2,
        },
        "calculated_at": now.isoformat(),
    }


def _demo_gap_analysis() -> dict:
    return {
        "total_gaps": 8,
        "critical_gaps": 2,
        "high_gaps": 3,
        "medium_gaps": 2,
        "low_gaps": 1,
        "gaps_by_entity": [
            {
                "entity_id": "entity-005",
                "entity_name": "Metro Heights",
                "gap_count": 3,
                "critical": 1,
                "gaps": [
                    {"rule": "Insurance Certificate Validity", "severity": "critical", "description": "Multiple insurance certificates expired"},
                    {"rule": "Safety Inspection Currency", "severity": "high", "description": "Safety inspection report over 12 months old"},
                    {"rule": "Business License Active", "severity": "high", "description": "Business license not on file"},
                ],
            },
            {
                "entity_id": "entity-003",
                "entity_name": "Oakmont Residences",
                "gap_count": 3,
                "critical": 1,
                "gaps": [
                    {"rule": "Business License Active", "severity": "critical", "description": "Business license has expired"},
                    {"rule": "Environmental Permit Coverage", "severity": "medium", "description": "Environmental permit pending review"},
                    {"rule": "Vendor Agreement Completeness", "severity": "low", "description": "1 vendor missing signed agreement"},
                ],
            },
            {
                "entity_id": "entity-001",
                "entity_name": "Sunrise Properties LLC",
                "gap_count": 2,
                "critical": 0,
                "gaps": [
                    {"rule": "Insurance Expiry Buffer", "severity": "high", "description": "Insurance policy expiring within 30 days"},
                    {"rule": "Vendor Agreement Review", "severity": "medium", "description": "Subcontractor agreement was rejected - needs resubmission"},
                ],
            },
        ],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/summary")
async def get_dashboard_summary(user: dict = Depends(get_current_user)):
    """Get dashboard summary statistics."""
    org_id = user.get("org_id", "")
    is_admin = user.get("role") == "admin"
    try:
        # Admin sees all data; non-admin filtered by org and ownership
        if is_admin:
            doc_filters = []
            entity_filters = []
            vendor_filters = None
        else:
            doc_filters = [("organization_id", "==", org_id)] if org_id else []
            entity_filters = [("organization_id", "==", org_id)] if org_id else []
            vendor_filters = [("organization_id", "==", org_id)] if org_id else None
            doc_filters.append(("uploaded_by", "==", user["user_id"]))
            entity_filters.append(("created_by", "==", user["user_id"]))
        docs = get_documents("documents", filters=doc_filters if doc_filters else None, limit=500)
        entities = get_documents("entities", filters=entity_filters if entity_filters else None, limit=100)
        vendors = get_documents("vendors", filters=vendor_filters, limit=100)
        # Always compute real stats (even if empty) — demo only used when Firestore throws
        if True:
            now = datetime.now(timezone.utc)
            # Separate active vs archived docs
            active_docs = [d for d in docs if d.get("status") != "archived"]
            expired = 0
            exp_30 = 0
            exp_60 = 0
            exp_90 = 0
            status_dist = {}
            type_dist = {}
            doc_scores = []
            for d in active_docs:
                st = d.get("status", "unknown")
                status_dist[st] = status_dist.get(st, 0) + 1
                dt = d.get("document_type", "Other")
                type_dist[dt] = type_dist.get(dt, 0) + 1
                # Collect document scores for fallback avg
                ds = d.get("score", 0)
                if isinstance(ds, (int, float)) and ds > 0:
                    doc_scores.append(ds)
                exp_str = d.get("expiry_date") or d.get("expiration_date")
                if exp_str:
                    try:
                        if isinstance(exp_str, str):
                            if len(exp_str) == 10:
                                exp = datetime.fromisoformat(exp_str + "T00:00:00+00:00")
                            else:
                                exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        else:
                            exp = exp_str
                        if exp < now:
                            expired += 1
                        elif exp < now + timedelta(days=30):
                            exp_30 += 1
                        elif exp < now + timedelta(days=60):
                            exp_60 += 1
                        elif exp < now + timedelta(days=90):
                            exp_90 += 1
                    except (ValueError, TypeError):
                        pass

            # Entity scores for avg
            entity_scores = []
            for ent in entities:
                s = ent.get("compliance_score", 0)
                if isinstance(s, (int, float)) and s > 0:
                    entity_scores.append(s)
            # Use entity scores if available, else fall back to doc scores
            if entity_scores:
                avg_score = round(sum(entity_scores) / len(entity_scores), 1)
            elif doc_scores:
                avg_score = round(sum(doc_scores) / len(doc_scores), 1)
            else:
                avg_score = 0

            # Risk distribution from entity scores
            risk_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for ent in entities:
                s = ent.get("compliance_score", 0)
                if isinstance(s, (int, float)):
                    if s >= 80:
                        risk_dist["low"] += 1
                    elif s >= 60:
                        risk_dist["medium"] += 1
                    elif s >= 40:
                        risk_dist["high"] += 1
                    else:
                        risk_dist["critical"] += 1

            # Activity feed — recent active documents sorted by updated_at/created_at
            activity = []
            sorted_docs = sorted(
                active_docs,
                key=lambda x: x.get("updated_at") or x.get("created_at") or "",
                reverse=True,
            )
            for d in sorted_docs[:10]:
                action = "uploaded"
                st = d.get("status", "")
                if st == "processed":
                    action = "processed"
                elif st == "approved":
                    action = "approved"
                elif st == "rejected":
                    action = "rejected"
                elif st == "expired":
                    action = "expired"
                activity.append({
                    "doc_id": d.get("id", ""),
                    "name": d.get("name", d.get("title", "")),
                    "action": action,
                    "entity_name": d.get("entity_name", ""),
                    "timestamp": d.get("updated_at") or d.get("created_at") or "",
                })

            return {
                "total_documents": len(active_docs),
                "total_entities": len(entities),
                "total_vendors": len(vendors),
                "expired": expired,
                "expiring_30d": exp_30,
                "expiring_60d": exp_60,
                "expiring_90d": exp_90,
                "avg_compliance_score": avg_score,
                "risk_distribution": risk_dist,
                "status_distribution": status_dist,
                "document_type_distribution": type_dist,
                "activity_feed": activity,
                "calculated_at": now.isoformat(),
            }
    except Exception:
        pass

    return _demo_summary()


@router.get("/trends")
async def get_compliance_trends(
    months: int = Query(6, ge=1, le=24),
    user: dict = Depends(get_current_user),
):
    """Get compliance score trends over time."""
    try:
        history = get_documents(
            "analytics_snapshots",
            order_by="date",
            direction="DESCENDING",
            limit=months,
        )
        if history:
            return {"trends": history, "months": months}
    except Exception:
        pass

    return {"trends": _demo_trends(months), "months": months}


@router.get("/risk-matrix")
async def get_risk_matrix(user: dict = Depends(get_current_user)):
    """Get risk matrix data (entities by risk level and score)."""
    try:
        org_id = user.get("org_id", "")
        filters = [("organization_id", "==", org_id)] if org_id else []
        if user.get("role") != "admin":
            filters.append(("created_by", "==", user["user_id"]))
        entities = get_documents("entities", filters=filters if filters else None, limit=100)
        if entities:
            matrix = []
            for ent in entities:
                score = calculate_entity_score(ent.get("id", ""))
                matrix.append({
                    "entity_id": ent.get("id", ""),
                    "entity_name": ent.get("name", ""),
                    "score": score.get("overall_score", 0),
                    "risk_level": score.get("risk_level", "unknown"),
                    "document_count": score.get("document_count", 0),
                })
            return {"matrix": matrix, "count": len(matrix)}
    except Exception:
        pass

    return {"matrix": _demo_risk_matrix(), "count": len(_demo_risk_matrix())}


@router.get("/expiry-forecast")
async def get_expiry_forecast(user: dict = Depends(get_current_user)):
    """Get upcoming document expirations in 30/60/90 day buckets."""
    try:
        org_id = user.get("org_id", "")
        filters = [("organization_id", "==", org_id)] if org_id else []
        if user.get("role") != "admin":
            filters.append(("uploaded_by", "==", user["user_id"]))
        docs = get_documents("documents", filters=filters if filters else None, limit=500)
        if docs:
            now = datetime.now(timezone.utc)
            buckets = {"overdue": [], "next_30_days": [], "next_60_days": [], "next_90_days": []}
            for d in docs:
                exp_str = d.get("expiry_date") or d.get("expiration_date")
                if not exp_str:
                    continue
                try:
                    if isinstance(exp_str, str):
                        exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    else:
                        exp = exp_str
                    delta = (exp - now).days
                    entry = {
                        "doc_id": d.get("id", ""),
                        "name": d.get("name", ""),
                        "entity_name": d.get("entity_name", ""),
                        "expiry_date": exp.isoformat(),
                        "document_type": d.get("document_type", ""),
                    }
                    if delta < 0:
                        entry["days_overdue"] = abs(delta)
                        buckets["overdue"].append(entry)
                    elif delta <= 30:
                        entry["days_until_expiry"] = delta
                        buckets["next_30_days"].append(entry)
                    elif delta <= 60:
                        entry["days_until_expiry"] = delta
                        buckets["next_60_days"].append(entry)
                    elif delta <= 90:
                        entry["days_until_expiry"] = delta
                        buckets["next_90_days"].append(entry)
                except (ValueError, TypeError):
                    pass
            return {
                "buckets": buckets,
                "summary": {
                    "overdue_count": len(buckets["overdue"]),
                    "next_30_count": len(buckets["next_30_days"]),
                    "next_60_count": len(buckets["next_60_days"]),
                    "next_90_count": len(buckets["next_90_days"]),
                },
                "calculated_at": now.isoformat(),
            }
    except Exception:
        pass

    return _demo_expiry_forecast()


@router.get("/vendor-exposure")
async def get_vendor_exposure(user: dict = Depends(get_current_user)):
    """Get vendor risk exposure summary."""
    org_id = user.get("org_id", "")
    return get_vendor_summary(org_id or "demo-org-001")


@router.get("/compliance-history")
async def get_compliance_history(
    months: int = Query(12, ge=1, le=36),
    user: dict = Depends(get_current_user),
):
    """Get historical compliance data (monthly snapshots)."""
    try:
        history = get_documents(
            "compliance_history",
            order_by="date",
            direction="DESCENDING",
            limit=months,
        )
        if history:
            return {"history": history, "months": months}
    except Exception:
        pass

    # Demo fallback
    now = datetime.now(timezone.utc)
    history = []
    for i in range(months, 0, -1):
        d = now - timedelta(days=30 * i)
        base = 58 + (months - i) * 2.5
        history.append({
            "date": d.strftime("%Y-%m"),
            "avg_score": round(min(base + (hash(str(i + 7)) % 6), 98), 1),
            "entity_count": 5,
            "compliant_entities": max(1, 5 - (i // 3)),
            "total_documents": 35 + (months - i) * 2,
            "critical_gaps": max(0, 4 - (months - i) // 2),
        })
    return {"history": history, "months": months}


@router.get("/gap-analysis")
async def get_gap_analysis(user: dict = Depends(get_current_user)):
    """Get organization-wide compliance gap analysis."""
    return _demo_gap_analysis()
