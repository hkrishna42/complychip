"""ComplyChip V3 - Shared FastAPI Dependencies"""
import logging
from fastapi import Request, HTTPException, Depends
from backend.services.auth_service import verify_access_token

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> dict:
    """Extract and verify JWT from Authorization header.

    Also validates that the session is still active (if session_id is in token).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth_header[7:]
    try:
        user = verify_access_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Validate session is still active (if session_id embedded in token)
    session_id = user.get("session_id", "")
    if session_id:
        try:
            from backend.services.firestore_service import get_document
            session = get_document("sessions", session_id)
            if session and not session.get("is_active", True):
                raise HTTPException(status_code=401, detail="Session has been revoked")
        except HTTPException:
            raise
        except Exception as e:
            # If Firestore is unavailable, allow the request (don't block on session check)
            logger.debug("Session validation skipped (Firestore unavailable): %s", e)

    return user


def require_roles(*roles: str):
    """FastAPI dependency factory for role-based access control."""
    async def _check(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _check
