"""ComplyChip V3 - Seed Demo Data

Populates Firestore with realistic demo data for development and testing.

Usage:
    python -m scripts.seed_data
    python -m scripts.seed_data --org default
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.config import get_firestore_client  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)


def _ts(days_offset: int = 0) -> datetime:
    """Return a UTC datetime shifted by *days_offset* from now."""
    return NOW + timedelta(days=days_offset)


def _id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------

ORG_ID = "default"

# -- Entities ---------------------------------------------------------------

ENTITY_IDS = [_id(), _id(), _id()]

ENTITIES = [
    {
        "id": ENTITY_IDS[0],
        "name": "Main Office",
        "entity_type": "property",
        "address": "100 Market St, San Francisco, CA 94105",
        "compliance_score": 87,
        "organization_id": ORG_ID,
        "metadata": {"sqft": 12000, "floors": 3},
    },
    {
        "id": ENTITY_IDS[1],
        "name": "West Coast Branch",
        "entity_type": "property",
        "address": "456 Sunset Blvd, Los Angeles, CA 90028",
        "compliance_score": 72,
        "organization_id": ORG_ID,
        "metadata": {"sqft": 8500, "floors": 2},
    },
    {
        "id": ENTITY_IDS[2],
        "name": "Downtown Property",
        "entity_type": "property",
        "address": "789 Broadway, New York, NY 10003",
        "compliance_score": 95,
        "organization_id": ORG_ID,
        "metadata": {"sqft": 15000, "floors": 5},
    },
]

# -- Documents --------------------------------------------------------------

DOC_IDS = [_id() for _ in range(8)]

DOCUMENTS = [
    {
        "id": DOC_IDS[0],
        "title": "Main Office Lease Agreement",
        "document_type": "lease_agreement",
        "entity_id": ENTITY_IDS[0],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(180),
        "upload_date": _ts(-90),
        "file_path": "documents/main-office-lease.pdf",
        "ai_metadata": {"confidence": 0.95, "extracted_clauses": 12},
    },
    {
        "id": DOC_IDS[1],
        "title": "Main Office Insurance Policy",
        "document_type": "insurance_policy",
        "entity_id": ENTITY_IDS[0],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(45),
        "upload_date": _ts(-300),
        "file_path": "documents/main-office-insurance.pdf",
        "ai_metadata": {"confidence": 0.91, "coverage_amount": 2000000},
    },
    {
        "id": DOC_IDS[2],
        "title": "West Coast Fire Safety Certificate",
        "document_type": "fire_safety_cert",
        "entity_id": ENTITY_IDS[1],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "expiring_soon",
        "expiry_date": _ts(15),
        "upload_date": _ts(-350),
        "file_path": "documents/west-coast-fire-cert.pdf",
        "ai_metadata": {"confidence": 0.88, "inspection_passed": True},
    },
    {
        "id": DOC_IDS[3],
        "title": "West Coast Building Permit",
        "document_type": "building_permit",
        "entity_id": ENTITY_IDS[1],
        "organization_id": ORG_ID,
        "status": "expired",
        "compliance_status": "non_compliant",
        "expiry_date": _ts(-30),
        "upload_date": _ts(-400),
        "file_path": "documents/west-coast-permit.pdf",
        "ai_metadata": {"confidence": 0.82, "permit_type": "commercial"},
    },
    {
        "id": DOC_IDS[4],
        "title": "Downtown Lease Agreement",
        "document_type": "lease_agreement",
        "entity_id": ENTITY_IDS[2],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(365),
        "upload_date": _ts(-60),
        "file_path": "documents/downtown-lease.pdf",
        "ai_metadata": {"confidence": 0.97, "extracted_clauses": 18},
    },
    {
        "id": DOC_IDS[5],
        "title": "Downtown Insurance Policy",
        "document_type": "insurance_policy",
        "entity_id": ENTITY_IDS[2],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(200),
        "upload_date": _ts(-120),
        "file_path": "documents/downtown-insurance.pdf",
        "ai_metadata": {"confidence": 0.93, "coverage_amount": 5000000},
    },
    {
        "id": DOC_IDS[6],
        "title": "Vendor Contract - SafeGuard Insurance",
        "document_type": "vendor_contract",
        "entity_id": ENTITY_IDS[0],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(90),
        "upload_date": _ts(-200),
        "file_path": "documents/vendor-safeguard.pdf",
        "ai_metadata": {"confidence": 0.90, "sla_terms": True},
    },
    {
        "id": DOC_IDS[7],
        "title": "Main Office Fire Safety Certificate",
        "document_type": "fire_safety_cert",
        "entity_id": ENTITY_IDS[0],
        "organization_id": ORG_ID,
        "status": "active",
        "compliance_status": "compliant",
        "expiry_date": _ts(270),
        "upload_date": _ts(-45),
        "file_path": "documents/main-office-fire-cert.pdf",
        "ai_metadata": {"confidence": 0.94, "inspection_passed": True},
    },
]

# -- Vendors ----------------------------------------------------------------

VENDOR_IDS = [_id(), _id(), _id()]

VENDORS = [
    {
        "id": VENDOR_IDS[0],
        "name": "SafeGuard Insurance",
        "category": "insurance",
        "risk_score": 15,
        "organization_id": ORG_ID,
        "contact_email": "contact@safeguardins.com",
        "status": "active",
        "last_review_date": _ts(-30),
    },
    {
        "id": VENDOR_IDS[1],
        "name": "Metro Maintenance Corp",
        "category": "facilities",
        "risk_score": 32,
        "organization_id": ORG_ID,
        "contact_email": "ops@metromaint.com",
        "status": "active",
        "last_review_date": _ts(-60),
    },
    {
        "id": VENDOR_IDS[2],
        "name": "Legal Associates LLP",
        "category": "legal",
        "risk_score": 8,
        "organization_id": ORG_ID,
        "contact_email": "info@legalassoc.com",
        "status": "active",
        "last_review_date": _ts(-15),
    },
]

# -- Compliance Rules -------------------------------------------------------

RULE_IDS = [_id() for _ in range(5)]

COMPLIANCE_RULES = [
    {
        "id": RULE_IDS[0],
        "name": "Lease Agreement Required",
        "rule_type": "required_document",
        "document_type": "lease_agreement",
        "description": "Every entity must have an active lease agreement on file.",
        "organization_id": ORG_ID,
        "is_active": True,
        "severity": "high",
    },
    {
        "id": RULE_IDS[1],
        "name": "Insurance Policy Required",
        "rule_type": "required_document",
        "document_type": "insurance_policy",
        "description": "Every entity must have a current insurance policy.",
        "organization_id": ORG_ID,
        "is_active": True,
        "severity": "high",
    },
    {
        "id": RULE_IDS[2],
        "name": "Fire Safety Certificate Required",
        "rule_type": "required_document",
        "document_type": "fire_safety_cert",
        "description": "Annual fire safety certificate must be maintained.",
        "organization_id": ORG_ID,
        "is_active": True,
        "severity": "high",
    },
    {
        "id": RULE_IDS[3],
        "name": "Document Expiry Warning (30 days)",
        "rule_type": "expiry_threshold",
        "threshold_days": 30,
        "description": "Flag documents expiring within the next 30 days.",
        "organization_id": ORG_ID,
        "is_active": True,
        "severity": "medium",
    },
    {
        "id": RULE_IDS[4],
        "name": "Document Expiry Critical (7 days)",
        "rule_type": "expiry_threshold",
        "threshold_days": 7,
        "description": "Critical alert for documents expiring within 7 days.",
        "organization_id": ORG_ID,
        "is_active": True,
        "severity": "critical",
    },
]

# -- Regulatory Alerts ------------------------------------------------------

ALERT_IDS = [_id(), _id(), _id()]

REGULATORY_ALERTS = [
    {
        "id": ALERT_IDS[0],
        "title": "Updated Fire Code Regulations",
        "description": "New fire code regulations effective Q2 require updated sprinkler system documentation.",
        "severity": "high",
        "category": "fire_safety",
        "effective_date": _ts(30),
        "organization_id": ORG_ID,
        "is_read": False,
        "source": "National Fire Protection Association",
    },
    {
        "id": ALERT_IDS[1],
        "title": "Commercial Lease Disclosure Update",
        "description": "State regulators mandate new disclosure addendum for commercial leases signed after July 1.",
        "severity": "medium",
        "category": "lease_compliance",
        "effective_date": _ts(90),
        "organization_id": ORG_ID,
        "is_read": False,
        "source": "State Real Estate Commission",
    },
    {
        "id": ALERT_IDS[2],
        "title": "Annual Insurance Minimum Coverage Adjustment",
        "description": "Minimum liability coverage for commercial properties increased to $2M.",
        "severity": "low",
        "category": "insurance",
        "effective_date": _ts(120),
        "organization_id": ORG_ID,
        "is_read": True,
        "source": "Department of Insurance",
    },
]

# -- Knowledge Graph Edges --------------------------------------------------

GRAPH_EDGES = [
    # --- Entity -> Document edges (green -> blue) ---
    {
        "id": _id(),
        "source_id": ENTITY_IDS[0],
        "source_type": "entity",
        "target_id": DOC_IDS[0],
        "target_type": "document",
        "relationship": "has_document",
        "description": "Main Office holds lease agreement.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": ENTITY_IDS[0],
        "source_type": "entity",
        "target_id": DOC_IDS[1],
        "target_type": "document",
        "relationship": "has_document",
        "description": "Main Office holds insurance policy.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": ENTITY_IDS[1],
        "source_type": "entity",
        "target_id": DOC_IDS[2],
        "target_type": "document",
        "relationship": "has_document",
        "description": "West Coast Branch holds fire safety certificate.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": ENTITY_IDS[1],
        "source_type": "entity",
        "target_id": DOC_IDS[3],
        "target_type": "document",
        "relationship": "has_document",
        "description": "West Coast Branch holds building permit.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": ENTITY_IDS[2],
        "source_type": "entity",
        "target_id": DOC_IDS[4],
        "target_type": "document",
        "relationship": "has_document",
        "description": "Downtown Property holds lease agreement.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": ENTITY_IDS[2],
        "source_type": "entity",
        "target_id": DOC_IDS[5],
        "target_type": "document",
        "relationship": "has_document",
        "description": "Downtown Property holds insurance policy.",
        "organization_id": ORG_ID,
    },
    # --- Vendor -> Document edges (orange -> blue) ---
    {
        "id": _id(),
        "source_id": VENDOR_IDS[0],
        "source_type": "vendor",
        "target_id": DOC_IDS[6],
        "target_type": "document",
        "relationship": "issued_by",
        "description": "SafeGuard Insurance issued the vendor contract.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": VENDOR_IDS[0],
        "source_type": "vendor",
        "target_id": DOC_IDS[1],
        "target_type": "document",
        "relationship": "provides",
        "description": "SafeGuard Insurance provides the insurance policy.",
        "organization_id": ORG_ID,
    },
    # --- Vendor -> Entity edges (orange -> green) ---
    {
        "id": _id(),
        "source_id": VENDOR_IDS[0],
        "source_type": "vendor",
        "target_id": ENTITY_IDS[0],
        "target_type": "entity",
        "relationship": "contracts_with",
        "description": "SafeGuard Insurance contracts with Main Office.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": VENDOR_IDS[1],
        "source_type": "vendor",
        "target_id": ENTITY_IDS[1],
        "target_type": "entity",
        "relationship": "contracts_with",
        "description": "Metro Maintenance serves West Coast Branch.",
        "organization_id": ORG_ID,
    },
    # --- Document -> Document edges (blue -> blue) ---
    {
        "id": _id(),
        "source_id": DOC_IDS[0],
        "source_type": "document",
        "target_id": DOC_IDS[1],
        "target_type": "document",
        "relationship": "requires",
        "description": "Lease agreement requires proof of insurance.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": DOC_IDS[0],
        "source_type": "document",
        "target_id": DOC_IDS[7],
        "target_type": "document",
        "relationship": "requires",
        "description": "Lease agreement requires fire safety certificate.",
        "organization_id": ORG_ID,
    },
    {
        "id": _id(),
        "source_id": DOC_IDS[2],
        "source_type": "document",
        "target_id": DOC_IDS[3],
        "target_type": "document",
        "relationship": "supersedes",
        "description": "Fire safety cert supersedes building permit.",
        "organization_id": ORG_ID,
    },
]

# -- Audit Log Entries ------------------------------------------------------

AUDIT_LOGS = [
    {
        "id": _id(),
        "action": "document.upload",
        "actor_email": "admin@complychip.ai",
        "entity_id": ENTITY_IDS[0],
        "resource_id": DOC_IDS[0],
        "resource_type": "document",
        "description": "Uploaded Main Office Lease Agreement.",
        "organization_id": ORG_ID,
        "timestamp": _ts(-90),
    },
    {
        "id": _id(),
        "action": "compliance.score_updated",
        "actor_email": "system",
        "entity_id": ENTITY_IDS[0],
        "resource_id": ENTITY_IDS[0],
        "resource_type": "entity",
        "description": "Compliance score recalculated: 87.",
        "organization_id": ORG_ID,
        "timestamp": _ts(-5),
    },
    {
        "id": _id(),
        "action": "document.upload",
        "actor_email": "admin@complychip.ai",
        "entity_id": ENTITY_IDS[1],
        "resource_id": DOC_IDS[2],
        "resource_type": "document",
        "description": "Uploaded West Coast Fire Safety Certificate.",
        "organization_id": ORG_ID,
        "timestamp": _ts(-350),
    },
    {
        "id": _id(),
        "action": "vendor.review",
        "actor_email": "admin@complychip.ai",
        "entity_id": None,
        "resource_id": VENDOR_IDS[1],
        "resource_type": "vendor",
        "description": "Vendor risk review completed for Metro Maintenance Corp.",
        "organization_id": ORG_ID,
        "timestamp": _ts(-60),
    },
    {
        "id": _id(),
        "action": "alert.acknowledged",
        "actor_email": "admin@complychip.ai",
        "entity_id": None,
        "resource_id": ALERT_IDS[2],
        "resource_type": "regulatory_alert",
        "description": "Acknowledged insurance coverage adjustment alert.",
        "organization_id": ORG_ID,
        "timestamp": _ts(-10),
    },
]

# -- Risk Predictions -------------------------------------------------------

RISK_PREDICTIONS = [
    {
        "id": _id(),
        "entity_id": ENTITY_IDS[1],
        "organization_id": ORG_ID,
        "risk_level": "high",
        "risk_score": 72,
        "factors": [
            "Expired building permit",
            "Fire safety certificate expiring in 15 days",
            "Below-average compliance score",
        ],
        "recommendation": "Immediately renew the building permit and schedule fire safety inspection.",
        "predicted_at": _ts(-1),
    },
    {
        "id": _id(),
        "entity_id": ENTITY_IDS[0],
        "organization_id": ORG_ID,
        "risk_level": "low",
        "risk_score": 18,
        "factors": [
            "Insurance policy expiring in 45 days",
        ],
        "recommendation": "Begin insurance renewal process within the next two weeks.",
        "predicted_at": _ts(-1),
    },
]


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

COLLECTION_MAP = {
    "entities": ENTITIES,
    "documents": DOCUMENTS,
    "vendors": VENDORS,
    "compliance_rules": COMPLIANCE_RULES,
    "regulatory_alerts": REGULATORY_ALERTS,
    "knowledge_graph": GRAPH_EDGES,
    "audit_log": AUDIT_LOGS,
    "risk_predictions": RISK_PREDICTIONS,
}


def seed_collection(db, collection_name: str, items: list[dict]) -> int:
    """Write a list of items to a Firestore collection. Returns the count written."""
    count = 0
    for item in items:
        doc_id = item.pop("id")
        item["created_at"] = item.get("created_at", NOW)
        item["updated_at"] = item.get("updated_at", NOW)
        db.collection(collection_name).document(doc_id).set(item)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data into Firestore for ComplyChip V3")
    parser.add_argument("--org", default=ORG_ID, help="Organization ID to associate data with")
    args = parser.parse_args()

    # Update ORG_ID for all records if overridden
    if args.org != ORG_ID:
        for items in COLLECTION_MAP.values():
            for item in items:
                if "organization_id" in item:
                    item["organization_id"] = args.org

    print("=" * 50)
    print("ComplyChip V3 -- Seed Demo Data")
    print("=" * 50)
    print()

    print("[1/2] Connecting to Firestore ...")
    db = get_firestore_client()
    if db is None:
        print("ERROR: Could not connect to Firestore. Check FIREBASE_CRED_PATH and credentials.")
        sys.exit(1)
    print("  Connected.")
    print()

    print("[2/2] Seeding collections ...")
    total = 0
    for collection_name, items in COLLECTION_MAP.items():
        try:
            count = seed_collection(db, collection_name, items)
            total += count
            print(f"  {collection_name:25s}  {count} record(s)")
        except Exception as exc:
            print(f"  ERROR seeding {collection_name}: {exc}")
    print()

    print(f"Done!  {total} total records written across {len(COLLECTION_MAP)} collections.")


if __name__ == "__main__":
    main()
