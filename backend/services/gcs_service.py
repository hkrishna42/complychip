"""ComplyChip V3 - Google Cloud Storage Service"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from backend.config import get_gcs_client, GCS_BUCKET


def _get_bucket():
    """Get the GCS bucket, or None if not configured."""
    client = get_gcs_client()
    if client is None:
        return None
    try:
        return client.bucket(GCS_BUCKET)
    except Exception as e:
        print(f"Warning: GCS bucket access failed: {e}")
        return None


def upload_file(
    file_data: bytes,
    filename: str,
    content_type: str,
    entity_id: str,
) -> str:
    """Upload a file to GCS and return the GCS path.

    Returns a GCS object path like 'entities/<entity_id>/<uuid>_<filename>'.
    Falls back to a demo path when GCS is not configured.
    """
    unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    gcs_path = f"entities/{entity_id}/{unique_name}"

    bucket = _get_bucket()
    if bucket is None:
        # Demo fallback
        return f"demo://{gcs_path}"

    try:
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(file_data, content_type=content_type)
        return gcs_path
    except Exception as e:
        print(f"Warning: GCS upload failed: {e}")
        return f"demo://{gcs_path}"


def generate_signed_url(gcs_path: str, expiration_minutes: int = 60) -> str:
    """Generate a signed download URL for a GCS object.

    Falls back to a placeholder URL when GCS is not configured.
    """
    if gcs_path.startswith("demo://"):
        return f"https://storage.example.com/{gcs_path.replace('demo://', '')}?signed=demo"

    bucket = _get_bucket()
    if bucket is None:
        return f"https://storage.example.com/{gcs_path}?signed=demo"

    try:
        blob = bucket.blob(gcs_path)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )
        return url
    except Exception as e:
        print(f"Warning: Signed URL generation failed: {e}")
        return f"https://storage.example.com/{gcs_path}?signed=demo"


def delete_file(gcs_path: str) -> bool:
    """Delete a file from GCS.

    Returns True on success (or if path is a demo path).
    """
    if gcs_path.startswith("demo://"):
        return True

    bucket = _get_bucket()
    if bucket is None:
        return True  # treat as no-op in demo mode

    try:
        blob = bucket.blob(gcs_path)
        blob.delete()
        return True
    except Exception as e:
        print(f"Warning: GCS delete failed: {e}")
        return False


def list_files(prefix: str, max_results: int = 100) -> list:
    """List files under a prefix in GCS.

    Returns a list of dicts with name, size, and updated timestamp.
    """
    bucket = _get_bucket()
    if bucket is None:
        return []

    try:
        blobs = bucket.list_blobs(prefix=prefix, max_results=max_results)
        return [
            {
                "name": blob.name,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None,
                "content_type": blob.content_type,
            }
            for blob in blobs
        ]
    except Exception as e:
        print(f"Warning: GCS list failed: {e}")
        return []
