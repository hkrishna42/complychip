"""ComplyChip V3 - Regulatory Intelligence Service"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.services.firestore_service import (
    get_documents,
    get_document,
    query_documents,
)


def get_regulatory_feed(
    organization_id: str,
    jurisdiction: Optional[str] = None,
    limit: int = 20,
) -> list:
    """Get regulatory alerts feed for an organization.

    Returns a list of regulatory alert dicts sorted by date descending.
    Falls back to demo alerts when Firestore is unavailable.
    """
    try:
        filters = [("organization_id", "==", organization_id)]
        if jurisdiction:
            filters.append(("jurisdiction", "==", jurisdiction))
        alerts = get_documents(
            "regulatory_alerts",
            filters=filters,
            order_by="published_date",
            direction="DESCENDING",
            limit=limit,
        )
    except Exception:
        alerts = []

    if not alerts:
        return _demo_regulatory_feed()

    return alerts


def match_alerts_to_entities(alert_id: str) -> dict:
    """Match a regulatory alert to affected entities.

    Returns the alert with a list of affected entity references.
    Falls back to demo data when Firestore is unavailable.
    """
    try:
        alert = get_document("regulatory_alerts", alert_id)
    except Exception:
        alert = None

    if not alert:
        return _demo_alert_match(alert_id)

    # Find entities in the same jurisdiction / affected categories
    jurisdiction = alert.get("jurisdiction", "")
    categories = alert.get("affected_categories", [])

    affected_entities = []
    try:
        if jurisdiction:
            entities = query_documents("entities", "jurisdiction", "==", jurisdiction)
            for ent in entities:
                ent_types = ent.get("document_types", [])
                overlap = set(categories) & set(ent_types) if categories else set()
                affected_entities.append({
                    "entity_id": ent.get("id", ""),
                    "entity_name": ent.get("name", ""),
                    "match_reason": f"Same jurisdiction ({jurisdiction})",
                    "affected_doc_types": list(overlap),
                    "impact_level": "high" if overlap else "medium",
                })
    except Exception:
        pass

    if not affected_entities:
        return _demo_alert_match(alert_id)

    return {
        "alert_id": alert_id,
        "alert_title": alert.get("title", ""),
        "jurisdiction": jurisdiction,
        "affected_entities": affected_entities,
        "total_affected": len(affected_entities),
    }


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_regulatory_feed() -> list:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "reg-alert-001",
            "title": "OSHA Updated Workplace Safety Standards 2026",
            "summary": "New requirements for fall protection equipment certification and annual inspection schedules.",
            "jurisdiction": "Federal - United States",
            "agency": "OSHA",
            "severity": "high",
            "status": "new",
            "affected_categories": ["Safety Certificate", "Environmental Permit"],
            "published_date": (now - timedelta(days=2)).isoformat(),
            "effective_date": (now + timedelta(days=90)).isoformat(),
            "url": "https://www.osha.gov/updates/2026",
        },
        {
            "id": "reg-alert-002",
            "title": "EPA Clean Air Act Amendments - Industrial Emissions",
            "summary": "Stricter emissions standards for commercial properties near residential zones.",
            "jurisdiction": "Federal - United States",
            "agency": "EPA",
            "severity": "critical",
            "status": "new",
            "affected_categories": ["Environmental Permit", "Business License"],
            "published_date": (now - timedelta(days=5)).isoformat(),
            "effective_date": (now + timedelta(days=180)).isoformat(),
            "url": "https://www.epa.gov/amendments/2026",
        },
        {
            "id": "reg-alert-003",
            "title": "California SB-1234: Data Privacy Requirements for Property Managers",
            "summary": "New data handling requirements for tenant personally identifiable information.",
            "jurisdiction": "State of California",
            "agency": "California Attorney General",
            "severity": "medium",
            "status": "reviewed",
            "affected_categories": ["NDA", "Vendor Agreement"],
            "published_date": (now - timedelta(days=14)).isoformat(),
            "effective_date": (now + timedelta(days=120)).isoformat(),
            "url": "https://leginfo.ca.gov/sb1234",
        },
        {
            "id": "reg-alert-004",
            "title": "DOL Contractor Classification Update",
            "summary": "Revised guidelines for independent contractor vs. employee classification.",
            "jurisdiction": "Federal - United States",
            "agency": "Department of Labor",
            "severity": "medium",
            "status": "acknowledged",
            "affected_categories": ["Employment Contract", "Vendor Agreement"],
            "published_date": (now - timedelta(days=21)).isoformat(),
            "effective_date": (now + timedelta(days=60)).isoformat(),
            "url": "https://www.dol.gov/contractor-update",
        },
        {
            "id": "reg-alert-005",
            "title": "New York Fire Code Revision - High-Rise Compliance",
            "summary": "Updated fire safety inspection requirements for buildings over 6 stories.",
            "jurisdiction": "State of New York",
            "agency": "NY Department of State",
            "severity": "high",
            "status": "new",
            "affected_categories": ["Safety Certificate", "Insurance Policy"],
            "published_date": (now - timedelta(days=3)).isoformat(),
            "effective_date": (now + timedelta(days=45)).isoformat(),
            "url": "https://dos.ny.gov/fire-code-2026",
        },
    ]


def _demo_alert_match(alert_id: str) -> dict:
    return {
        "alert_id": alert_id,
        "alert_title": "Regulatory Alert",
        "jurisdiction": "Federal - United States",
        "affected_entities": [
            {
                "entity_id": "entity-001",
                "entity_name": "Sunrise Properties LLC",
                "match_reason": "Same jurisdiction (Federal - United States)",
                "affected_doc_types": ["Safety Certificate"],
                "impact_level": "high",
            },
            {
                "entity_id": "entity-002",
                "entity_name": "Harbor View Complex",
                "match_reason": "Same jurisdiction (Federal - United States)",
                "affected_doc_types": ["Environmental Permit"],
                "impact_level": "medium",
            },
        ],
        "total_affected": 2,
    }
