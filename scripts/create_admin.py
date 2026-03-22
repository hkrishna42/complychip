"""ComplyChip V3 - Create Initial Admin User

Usage:
    python -m scripts.create_admin
    python -m scripts.create_admin --email admin@example.com --name "My Admin" --password secret
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Ensure the project root is on sys.path so `backend.*` imports resolve
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.config import get_firestore_client  # noqa: E402
from backend.services.auth_service import hash_password  # noqa: E402


DEFAULT_EMAIL = "admin@complychip.ai"
DEFAULT_NAME = "Admin User"
DEFAULT_PASSWORD = "admin123"
DEFAULT_ORG_ID = "default"
DEFAULT_ORG_NAME = "Default Organization"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an initial admin user for ComplyChip V3")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"Admin email (default: {DEFAULT_EMAIL})")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"Admin display name (default: {DEFAULT_NAME})")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Admin password (default: admin123)")
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID, help=f"Organization ID (default: {DEFAULT_ORG_ID})")
    parser.add_argument("--org-name", default=DEFAULT_ORG_NAME, help=f"Organization name (default: {DEFAULT_ORG_NAME})")
    return parser.parse_args()


def create_default_organization(db, org_id: str, org_name: str) -> None:
    """Create a default organization document if it does not already exist."""
    org_ref = db.collection("organizations").document(org_id)
    existing = org_ref.get()
    if existing.exists:
        print(f"  Organization '{org_id}' already exists -- skipping.")
        return

    now = datetime.now(timezone.utc)
    org_data = {
        "name": org_name,
        "industry": "general",
        "created_at": now,
        "updated_at": now,
        "is_active": True,
        "settings": {},
    }
    org_ref.set(org_data)
    print(f"  Created organization: {org_name} (id={org_id})")


def create_admin_user(db, email: str, name: str, password: str, org_id: str) -> None:
    """Create the admin user document in the users collection."""
    # Check for existing user with same email
    existing = db.collection("users").where("email", "==", email).limit(1).stream()
    for doc in existing:
        print(f"  User with email '{email}' already exists (id={doc.id}) -- skipping.")
        return

    now = datetime.now(timezone.utc)
    user_id = str(uuid4())
    password_hash = hash_password(password)

    user_data = {
        "email": email,
        "name": name,
        "password_hash": password_hash,
        "role": "admin",
        "organization_id": org_id,
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }

    db.collection("users").document(user_id).set(user_data)
    print(f"  Created admin user: {name} <{email}> (id={user_id})")


def main() -> None:
    args = parse_args()

    print("=" * 50)
    print("ComplyChip V3 -- Create Admin User")
    print("=" * 50)
    print()

    print("[1/3] Connecting to Firestore ...")
    db = get_firestore_client()
    if db is None:
        print("ERROR: Could not connect to Firestore. Check FIREBASE_CRED_PATH and credentials.")
        sys.exit(1)
    print("  Connected to Firestore.")
    print()

    print("[2/3] Creating default organization ...")
    try:
        create_default_organization(db, args.org_id, args.org_name)
    except Exception as exc:
        print(f"ERROR: Failed to create organization: {exc}")
        sys.exit(1)
    print()

    print("[3/3] Creating admin user ...")
    try:
        create_admin_user(db, args.email, args.name, args.password, args.org_id)
    except Exception as exc:
        print(f"ERROR: Failed to create admin user: {exc}")
        sys.exit(1)
    print()

    print("Done!  You can now log in with:")
    print(f"  Email:    {args.email}")
    print(f"  Password: {args.password}")


if __name__ == "__main__":
    main()
