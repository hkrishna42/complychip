"""ComplyChip V3 - Shared FastAPI Dependencies"""
from fastapi import Request, HTTPException, Depends
from backend.services.auth_service import verify_access_token


async def get_current_user(request: Request) -> dict:
    """Extract and verify JWT from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth_header[7:]
    try:
        return verify_access_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def require_roles(*roles: str):
    """FastAPI dependency factory for role-based access control."""
    async def _check(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _check
