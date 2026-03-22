"""ComplyChip V3 - Migrate Data from V2

Reads V2 Firestore collections (properties, documents, users) and maps them
into the V3 schema (entities, documents, users).

Usage:
    python -m scripts.migrate_v2 --dry-run       # preview without writing
    python -m scripts.migrate_v2                  # perform migration
    python -m scripts.migrate_v2 --org myorg      # set target org ID
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.config import get_firestore_client  # noqa: E402

DEFAULT_ORG_ID = "default"
DEFAULT_ORG_NAME = "Default Organization"

# ---------------------------------------------------------------------------
# V2 -> V3 mapping helpers
# ---------------------------------------------------------------------------

# Map V2 compliance status strings to the normalised V3 values
STATUS_MAP = {
    "valid": "compliant",
    "compliant": "compliant",
    "expired": "non_compliant",
    "non_compliant": "non_compliant",
    "expiring_soon": "expiring_soon",
    "pending": "pending_review",
    "pending_review": "pending_review",
}


def _normalize_status(raw: str) -> str:
    return STATUS_MAP.get(raw.lower().strip(), "pending_review")


def _map_property_to_entity(prop: dict, doc_id: str, org_id: str) -> dict:
    """Convert a V2 property document into a V3 entity document."""
    now = datetime.now(timezone.utc)
    return {
        "name": prop.get("name", prop.get("property_name", "Unnamed")),
        "entity_type": "property",
        "address": prop.get("address", ""),
        "compliance_score": prop.get("compliance_score", 0),
        "organization_id": org_id,
        "metadata": {
            "v2_property_id": doc_id,
            "migrated_at": now.isoformat(),
        },
        "created_at": prop.get("created_at", now),
        "updated_at": now,
    }


def _map_document(doc: dict, doc_id: str, property_id_map: dict, org_id: str) -> dict:
    """Convert a V2 document record into V3 format."""
    now = datetime.now(timezone.utc)

    # Resolve the entity_id -- V2 uses property_id or property
    v2_prop_id = doc.get("property_id", doc.get("property", ""))
    entity_id = property_id_map.get(v2_prop_id, v2_prop_id)

    return {
        "title": doc.get("title", doc.get("document_name", "Untitled")),
        "document_type": doc.get("document_type", doc.get("type", "other")),
        "entity_id": entity_id,
        "organization_id": org_id,
        "status": doc.get("status", "active"),
        "compliance_status": _normalize_status(
            doc.get("compliance_status", doc.get("status", "pending"))
        ),
        "expiry_date": doc.get("expiry_date", doc.get("expiration_date", None)),
        "upload_date": doc.get("upload_date", doc.get("created_at", now)),
        "file_path": doc.get("file_path", doc.get("gcs_path", "")),
        "ai_metadata": doc.get("ai_metadata", {}),
        "document_company_name": doc.get("document_company_name", ""),
        "metadata": {
            "v2_document_id": doc_id,
            "migrated_at": now.isoformat(),
        },
        "created_at": doc.get("created_at", now),
        "updated_at": now,
    }


V2_ROLE_MAP = {
    "admin": "admin",
    "manager": "manager",
    "viewer": "viewer",
    "user": "viewer",
}


def _map_user(user: dict, doc_id: str, org_id: str) -> dict:
    """Convert a V2 user record into V3 format."""
    now = datetime.now(timezone.utc)
    return {
        "email": user.get("email", ""),
        "name": user.get("name", user.get("display_name", "")),
        "password_hash": user.get("password_hash", user.get("hashed_password", "")),
        "role": V2_ROLE_MAP.get(user.get("role", "viewer"), "viewer"),
        "organization_id": org_id,
        "is_active": user.get("is_active", True),
        "metadata": {
            "v2_user_id": doc_id,
            "migrated_at": now.isoformat(),
        },
        "created_at": user.get("created_at", now),
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def _read_collection(db, name: str) -> list[tuple[str, dict]]:
    """Read all documents from a Firestore collection and return (id, data) tuples."""
    docs = db.collection(name).stream()
    results = []
    for doc in docs:
        results.append((doc.id, doc.to_dict()))
    return results


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------


def migrate(db, org_id: str, dry_run: bool) -> dict:
    """Run the full migration. Returns a summary dict with counts."""
    summary = {"entities": 0, "documents": 0, "users": 0, "organization": 0}

    # --- Organization ---
    print("  Creating default organization ...")
    if not dry_run:
        now = datetime.now(timezone.utc)
        org_ref = db.collection("organizations").document(org_id)
        if not org_ref.get().exists:
            org_ref.set({
                "name": DEFAULT_ORG_NAME,
                "industry": "general",
                "created_at": now,
                "updated_at": now,
                "is_active": True,
                "settings": {},
            })
            summary["organization"] = 1
            print(f"    Created organization '{org_id}'.")
        else:
            print(f"    Organization '{org_id}' already exists -- skipped.")
    else:
        print(f"    [DRY RUN] Would create organization '{org_id}'.")
        summary["organization"] = 1

    # --- Properties -> Entities ---
    print("  Reading V2 properties ...")
    v2_properties = _read_collection(db, "properties")
    print(f"    Found {len(v2_properties)} V2 properties.")

    property_id_map: dict[str, str] = {}  # V2 prop id -> V3 entity id

    for v2_id, prop_data in v2_properties:
        new_entity_id = str(uuid4())
        property_id_map[v2_id] = new_entity_id
        entity_data = _map_property_to_entity(prop_data, v2_id, org_id)

        if dry_run:
            print(f"    [DRY RUN] Would migrate property '{entity_data['name']}' -> entity {new_entity_id}")
        else:
            db.collection("entities").document(new_entity_id).set(entity_data)
            print(f"    Migrated property '{entity_data['name']}' -> entity {new_entity_id}")
        summary["entities"] += 1

    # --- Documents ---
    print("  Reading V2 documents ...")
    v2_documents = _read_collection(db, "documents")
    print(f"    Found {len(v2_documents)} V2 documents.")

    for v2_id, doc_data in v2_documents:
        new_doc_id = str(uuid4())
        doc_v3 = _map_document(doc_data, v2_id, property_id_map, org_id)

        if dry_run:
            print(f"    [DRY RUN] Would migrate document '{doc_v3['title']}' -> {new_doc_id}")
        else:
            db.collection("documents").document(new_doc_id).set(doc_v3)
            print(f"    Migrated document '{doc_v3['title']}' -> {new_doc_id}")
        summary["documents"] += 1

    # --- Users ---
    print("  Reading V2 users ...")
    v2_users = _read_collection(db, "users")
    print(f"    Found {len(v2_users)} V2 users.")

    for v2_id, user_data in v2_users:
        new_user_id = str(uuid4())
        user_v3 = _map_user(user_data, v2_id, org_id)

        if dry_run:
            print(f"    [DRY RUN] Would migrate user '{user_v3['email']}' -> {new_user_id}")
        else:
            db.collection("users").document(new_user_id).set(user_v3)
            print(f"    Migrated user '{user_v3['email']}' -> {new_user_id}")
        summary["users"] += 1

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate V2 Firestore data to V3 schema")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without writing to Firestore")
    parser.add_argument("--org", default=DEFAULT_ORG_ID, help=f"Target organization ID (default: {DEFAULT_ORG_ID})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 50)
    print("ComplyChip V3 -- Migrate from V2")
    if args.dry_run:
        print("  *** DRY RUN -- no data will be written ***")
    print("=" * 50)
    print()

    print("[1/2] Connecting to Firestore ...")
    db = get_firestore_client()
    if db is None:
        print("ERROR: Could not connect to Firestore. Check FIREBASE_CRED_PATH and credentials.")
        sys.exit(1)
    print("  Connected.")
    print()

    print("[2/2] Running migration ...")
    try:
        summary = migrate(db, args.org, args.dry_run)
    except Exception as exc:
        print(f"ERROR: Migration failed: {exc}")
        sys.exit(1)
    print()

    print("-" * 50)
    print("Migration Summary:")
    print(f"  Organizations created: {summary['organization']}")
    print(f"  Entities migrated:     {summary['entities']}")
    print(f"  Documents migrated:    {summary['documents']}")
    print(f"  Users migrated:        {summary['users']}")
    total = summary["entities"] + summary["documents"] + summary["users"]
    print(f"  Total records:         {total}")
    if args.dry_run:
        print()
        print("  Re-run without --dry-run to perform the actual migration.")
    print("-" * 50)


if __name__ == "__main__":
    main()
