"""ComplyChip V3 - Audit Logging Middleware

ASGI middleware that records mutating HTTP requests (POST, PUT, DELETE, PATCH)
to a Firestore ``audit_log`` collection.  JWT decoding is *unverified* here
because the middleware only needs the ``uid`` claim for logging; actual
authentication is handled by the ``dependencies`` module.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("complychip.audit")

# HTTP methods that represent state-changing operations
_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# URL path prefixes that should not generate audit entries
_SKIP_PREFIXES = ("/auth/", "/webhooks/")


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """Decode the JWT payload **without** signature verification.

    This is intentionally unverified because we only need the ``uid``
    field for the audit record.  Real authentication happens elsewhere.
    """
    try:
        # JWT structure: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Add padding so base64 doesn't complain
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:
        return None


def _extract_resource_info(path: str) -> tuple[str, Optional[str]]:
    """Derive ``resource_type`` and ``resource_id`` from the URL path.

    For a path like ``/api/documents/abc123`` the resource type is
    ``documents`` and the resource id is ``abc123``.

    Returns
    -------
    tuple[str, Optional[str]]
        (resource_type, resource_id) where resource_id may be ``None``.
    """
    segments = [s for s in path.strip("/").split("/") if s]
    # Skip the leading "api" segment if present
    if segments and segments[0] == "api":
        segments = segments[1:]
    resource_type = segments[0] if segments else "unknown"
    resource_id = segments[1] if len(segments) > 1 else None
    return resource_type, resource_id


async def _write_audit_log(
    user_id: str,
    method: str,
    resource_type: str,
    resource_id: Optional[str],
    ip_address: str,
    status_code: int,
) -> None:
    """Persist a single audit record to Firestore (fire-and-forget)."""
    try:
        from backend.config import get_firestore_client

        db = get_firestore_client()
        if db is None:
            logger.warning("Firestore client unavailable; audit log entry skipped.")
            return

        doc = {
            "user_id": user_id,
            "action": method,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ip_address": ip_address,
            "status_code": status_code,
        }
        db.collection("audit_log").add(doc)
    except Exception:
        logger.exception("Failed to write audit log entry")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that logs mutating requests to Firestore."""

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method.upper()

        # Only log mutating requests
        if method not in _MUTATING_METHODS:
            return await call_next(request)

        path = request.url.path

        # Skip noisy or sensitive endpoints
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        # Extract user id from the Authorization header (best-effort)
        user_id = "anonymous"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = _decode_jwt_payload(token)
            if payload:
                user_id = payload.get("uid", payload.get("sub", "anonymous"))

        resource_type, resource_id = _extract_resource_info(path)
        ip_address = request.client.host if request.client else "unknown"

        # Process the actual request first
        response = await call_next(request)

        # Fire-and-forget: schedule the Firestore write without blocking
        asyncio.create_task(
            _write_audit_log(
                user_id=user_id,
                method=method,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                status_code=response.status_code,
            )
        )

        return response
