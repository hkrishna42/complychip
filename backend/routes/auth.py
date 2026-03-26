"""ComplyChip V3 - Authentication Routes

Includes email/password login, Google OAuth sign-in, session management,
enhanced user profile, and logout.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from backend.services.auth_service import (
    hash_password, verify_password, create_token_pair, verify_refresh_token,
)
from backend.services.firestore_service import (
    get_user_by_email, create_document, get_document, update_document,
    query_documents, get_documents,
)
from backend.dependencies import get_current_user, require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    role: str = "viewer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    preferences: Optional[dict] = None


class GoogleCallbackRequest(BaseModel):
    code: str
    redirect_uri: str = ""


class GoogleLinkRequest(BaseModel):
    code: str
    redirect_uri: str = ""


# ---------------------------------------------------------------------------
# Demo mode fallback (when Firestore is unavailable)
# ---------------------------------------------------------------------------

DEMO_USERS = {
    "admin@complychip.ai": {
        "id": "demo-admin-001",
        "email": "admin@complychip.ai",
        "password": "$2b$12$LJ3m4ys3Lz0JVkQj5K8yXOYqGfVN8nT0XuGvK3mR5tP7w9hE6dOiG",  # admin123
        "name": "Admin User",
        "role": "admin",
        "organization_id": "demo-org-001",
    }
}


# ---------------------------------------------------------------------------
# Google OAuth helpers
# ---------------------------------------------------------------------------

_GOOGLE_CLIENT_CONFIG: Optional[dict] = None


def _load_google_client_config() -> dict:
    """Load Google Sign-In OAuth client config.

    Priority:
    1. GOOGLE_SIGNIN_CLIENT_ID / GOOGLE_SIGNIN_CLIENT_SECRET env vars
    2. google-signin-credentials.json file
    3. google-drive-credentials.json file (fallback)
    """
    global _GOOGLE_CLIENT_CONFIG
    if _GOOGLE_CLIENT_CONFIG is not None:
        return _GOOGLE_CLIENT_CONFIG

    # 1. Env vars (highest priority)
    env_id = os.environ.get("GOOGLE_SIGNIN_CLIENT_ID", "")
    env_secret = os.environ.get("GOOGLE_SIGNIN_CLIENT_SECRET", "")
    if env_id and env_secret:
        _GOOGLE_CLIENT_CONFIG = {"client_id": env_id, "client_secret": env_secret}
        logger.info("Using Google Sign-In credentials from environment variables")
        return _GOOGLE_CLIENT_CONFIG

    # 2. Credential files
    project_root = Path(__file__).parent.parent.parent
    candidates = [
        project_root / "google-signin-credentials.json",
        project_root.parent / "google-signin-credentials.json",
        project_root / "google-drive-credentials.json",
        project_root.parent / "google-drive-credentials.json",
    ]
    for p in candidates:
        if p.exists():
            with open(p, "r") as f:
                data = json.load(f)
            cfg = data.get("web") or data.get("installed") or data
            _GOOGLE_CLIENT_CONFIG = cfg
            logger.info("Loaded Google OAuth client config from %s", p)
            return _GOOGLE_CLIENT_CONFIG

    raise RuntimeError(
        "Google Sign-In credentials not found. Set GOOGLE_SIGNIN_CLIENT_ID/SECRET env vars or provide google-signin-credentials.json."
    )


def _get_google_client_id_secret() -> "tuple[str, str]":
    cfg = _load_google_client_config()
    return cfg["client_id"], cfg["client_secret"]


async def _exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens via Google token endpoint."""
    client_id, client_secret = _get_google_client_id_secret()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if resp.status_code != 200:
            logger.error("Google token exchange failed: %s", resp.text)
            raise HTTPException(status_code=400, detail="Failed to exchange Google auth code")
        return resp.json()


async def _fetch_google_userinfo(access_token: str) -> dict:
    """Fetch user profile from Google userinfo endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            logger.error("Google userinfo fetch failed: %s", resp.text)
            raise HTTPException(status_code=400, detail="Failed to fetch Google user profile")
        return resp.json()


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _create_session(user_id: str, token_jti: str, request: Request,
                    login_method: str = "email") -> str:
    """Create a session record in Firestore and return the session doc ID."""
    session_data = {
        "user_id": user_id,
        "token_jti": token_jti,
        "device_info": request.headers.get("User-Agent", "unknown"),
        "ip_address": request.client.host if request.client else "unknown",
        "last_active": datetime.now(timezone.utc),
        "is_active": True,
        "login_method": login_method,
    }
    session_id = create_document("sessions", session_data)
    return session_id


# ---------------------------------------------------------------------------
# Existing endpoints (preserved)
# ---------------------------------------------------------------------------

@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Authenticate user and return JWT token pair."""
    # Try Firestore first
    user = get_user_by_email(body.email)

    if user:
        stored_pw = user.get("password_hash") or user.get("password", "")
        if not stored_pw or not verify_password(body.password, stored_pw):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Update last_login
        update_document("users", user["id"], {"last_login": datetime.now(timezone.utc)})

        tokens = create_token_pair(
            user_id=user["id"],
            role=user.get("role", "viewer"),
            email=user["email"],
            org_id=user.get("organization_id", ""),
        )
        # Create session
        session_id = _create_session(
            user["id"], tokens["token_jti"], request, login_method="email"
        )
        # Re-create tokens with session_id embedded
        tokens = create_token_pair(
            user_id=user["id"],
            role=user.get("role", "viewer"),
            email=user["email"],
            org_id=user.get("organization_id", ""),
            session_id=session_id,
        )
        return {
            **tokens,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name", ""),
                "role": user.get("role", "viewer"),
                "organization_id": user.get("organization_id", ""),
                "avatar_url": user.get("avatar_url"),
            },
        }

    # Demo mode fallback
    demo = DEMO_USERS.get(body.email)
    if demo and body.password == "admin123":
        tokens = create_token_pair(
            user_id=demo["id"],
            role=demo["role"],
            email=demo["email"],
            org_id=demo["organization_id"],
        )
        return {
            **tokens,
            "token_type": "bearer",
            "user": {
                "id": demo["id"],
                "email": demo["email"],
                "name": demo["name"],
                "role": demo["role"],
                "organization_id": demo["organization_id"],
            },
        }

    raise HTTPException(status_code=401, detail="Invalid email or password")


@router.post("/register")
async def register(body: RegisterRequest, user: dict = Depends(require_roles("admin"))):
    """Create a new user (admin only)."""
    existing = get_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user_data = {
        "email": body.email,
        "password": hash_password(body.password),
        "name": body.name,
        "role": body.role,
        "organization_id": user.get("org_id", ""),
        "is_active": True,
        "auth_provider": "email",
        "preferences": {
            "dark_mode": False,
            "notification_email": True,
            "timezone": "America/New_York",
        },
    }
    user_id = create_document("users", user_data)
    return {
        "user_id": user_id,
        "email": body.email,
        "name": body.name,
        "role": body.role,
        "message": "User created successfully",
    }


@router.post("/refresh")
async def refresh_token(body: RefreshRequest):
    """Refresh access token using refresh token."""
    try:
        payload = verify_refresh_token(body.refresh_token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Check session is still active
    session_id = payload.get("session_id", "")
    if session_id:
        session = get_document("sessions", session_id)
        if session and not session.get("is_active", True):
            raise HTTPException(status_code=401, detail="Session has been revoked")
        # Update last_active
        if session:
            update_document("sessions", session_id, {
                "last_active": datetime.now(timezone.utc),
            })

    user = get_document("users", payload["user_id"])
    if not user:
        # Demo fallback
        for demo in DEMO_USERS.values():
            if demo["id"] == payload["user_id"]:
                tokens = create_token_pair(demo["id"], demo["role"], demo["email"],
                                           demo["organization_id"])
                return {**tokens, "token_type": "bearer"}
        raise HTTPException(status_code=401, detail="User not found")

    tokens = create_token_pair(
        user["id"], user.get("role", "viewer"), user["email"],
        user.get("organization_id", ""), session_id=session_id,
    )
    return {**tokens, "token_type": "bearer"}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user profile (enhanced)."""
    full_user = get_document("users", user["user_id"])
    if full_user:
        # Count active sessions
        active_sessions = query_documents("sessions", "user_id", "==", user["user_id"])
        active_count = sum(1 for s in active_sessions if s.get("is_active", False))

        has_password = bool(full_user.get("password_hash") or full_user.get("password"))
        has_google = bool(full_user.get("google_id"))

        # Determine auth_provider display value
        if has_password and has_google:
            auth_provider = "both"
        elif has_google:
            auth_provider = "google"
        else:
            auth_provider = "email"

        return {
            "id": full_user["id"],
            "email": full_user["email"],
            "name": full_user.get("name", ""),
            "role": full_user.get("role", "viewer"),
            "avatar_url": full_user.get("avatar_url"),
            "auth_provider": auth_provider,
            "organization_id": full_user.get("organization_id", ""),
            "preferences": full_user.get("preferences", {}),
            "last_login": full_user.get("last_login"),
            "created_at": full_user.get("created_at"),
            "has_password": has_password,
            "has_google": has_google,
            "active_sessions": active_count,
        }
    # Demo fallback
    return {
        "id": user["user_id"],
        "email": user["email"],
        "name": "Admin User",
        "role": user["role"],
        "avatar_url": None,
        "auth_provider": "email",
        "organization_id": user.get("org_id", ""),
        "preferences": {"dark_mode": False},
        "last_login": None,
        "created_at": None,
        "has_password": True,
        "has_google": False,
        "active_sessions": 0,
    }


@router.put("/me")
async def update_me(body: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    """Update current user profile."""
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.preferences is not None:
        updates["preferences"] = body.preferences
    if updates:
        update_document("users", user["user_id"], updates)
    return {"message": "Profile updated", "updated_fields": list(updates.keys())}


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """Change current user's password."""
    full_user = get_document("users", user["user_id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="User not found")
    stored_pw = full_user.get("password_hash") or full_user.get("password", "")
    if not stored_pw or not verify_password(body.current_password, stored_pw):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    update_document("users", user["user_id"], {"password_hash": hash_password(body.new_password)})
    return {"message": "Password changed successfully"}


# ---------------------------------------------------------------------------
# Google OAuth endpoints
# ---------------------------------------------------------------------------

@router.get("/google/url")
async def google_auth_url(request: Request, redirect_uri: str = ""):
    """Return the Google OAuth authorization URL for sign-in."""
    try:
        client_id, _ = _get_google_client_id_secret()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not redirect_uri:
        redirect_uri = f"{request.base_url}auth/google/callback"

    scopes = "openid email profile"
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return {"auth_url": auth_url, "redirect_uri": redirect_uri}


@router.post("/google/callback")
async def google_callback(body: GoogleCallbackRequest, request: Request):
    """Exchange Google auth code for tokens, create/update user, return JWT."""
    redirect_uri = body.redirect_uri or f"{request.base_url}auth/google/callback"

    # Exchange code for Google tokens
    google_tokens = await _exchange_google_code(body.code, redirect_uri)
    google_access_token = google_tokens.get("access_token")
    if not google_access_token:
        raise HTTPException(status_code=400, detail="No access token returned from Google")

    # Fetch user profile from Google
    profile = await _fetch_google_userinfo(google_access_token)
    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    google_id = profile.get("sub", "")
    name = profile.get("name", "")
    avatar_url = profile.get("picture", "")

    # Look up user in Firestore
    user = get_user_by_email(email)

    if user:
        # Existing user — update Google fields
        update_document("users", user["id"], {
            "google_id": google_id,
            "avatar_url": avatar_url,
            "last_login": datetime.now(timezone.utc),
            "auth_provider": "both" if (user.get("password_hash") or user.get("password")) else "google",
        })
        user_id = user["id"]
        role = user.get("role", "viewer")
        org_id = user.get("organization_id", "")
        user_name = user.get("name") or name
    else:
        # Auto-create new user
        user_data = {
            "email": email,
            "name": name,
            "role": "viewer",
            "organization_id": "default",
            "is_active": True,
            "auth_provider": "google",
            "google_id": google_id,
            "avatar_url": avatar_url,
            "last_login": datetime.now(timezone.utc),
            "preferences": {
                "dark_mode": False,
                "notification_email": True,
                "timezone": "America/New_York",
            },
        }
        user_id = create_document("users", user_data)
        role = "viewer"
        org_id = "default"
        user_name = name

    # Create JWT tokens (first pass to get jti)
    tokens = create_token_pair(
        user_id=user_id, role=role, email=email, org_id=org_id,
    )
    # Create session
    session_id = _create_session(user_id, tokens["token_jti"], request, login_method="google")
    # Re-create tokens with session_id
    tokens = create_token_pair(
        user_id=user_id, role=role, email=email, org_id=org_id,
        session_id=session_id,
    )

    return {
        **tokens,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "name": user_name,
            "role": role,
            "avatar_url": avatar_url,
        },
    }


@router.post("/google/link")
async def google_link(body: GoogleLinkRequest, request: Request,
                      user: dict = Depends(get_current_user)):
    """Link a Google account to the currently authenticated user."""
    redirect_uri = body.redirect_uri or f"{request.base_url}auth/google/callback"

    google_tokens = await _exchange_google_code(body.code, redirect_uri)
    google_access_token = google_tokens.get("access_token")
    if not google_access_token:
        raise HTTPException(status_code=400, detail="No access token returned from Google")

    profile = await _fetch_google_userinfo(google_access_token)
    google_id = profile.get("sub", "")
    avatar_url = profile.get("picture", "")

    update_document("users", user["user_id"], {
        "google_id": google_id,
        "avatar_url": avatar_url,
    })

    full_user = get_document("users", user["user_id"])
    return {
        "message": "Google account linked successfully",
        "user": {
            "id": full_user["id"],
            "email": full_user["email"],
            "name": full_user.get("name", ""),
            "avatar_url": avatar_url,
            "google_id": google_id,
        },
    }


@router.post("/google/unlink")
async def google_unlink(user: dict = Depends(get_current_user)):
    """Unlink Google account from the current user (only if password is set)."""
    full_user = get_document("users", user["user_id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="User not found")

    has_password = bool(full_user.get("password_hash") or full_user.get("password"))
    if not has_password:
        raise HTTPException(
            status_code=400,
            detail="Cannot unlink Google — you have no password set. "
                   "Set a password first so you can still log in.",
        )

    from google.cloud.firestore_v1 import DELETE_FIELD
    # Remove google_id; keep avatar_url if desired
    update_document("users", user["user_id"], {
        "google_id": DELETE_FIELD,
        "auth_provider": "email",
    })
    return {"message": "Google account unlinked successfully"}


# ---------------------------------------------------------------------------
# Session management endpoints
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    """List all active sessions for the current user."""
    sessions = query_documents("sessions", "user_id", "==", user["user_id"])
    active = [
        {
            "id": s["id"],
            "device_info": s.get("device_info", ""),
            "ip_address": s.get("ip_address", ""),
            "created_at": s.get("created_at"),
            "last_active": s.get("last_active"),
            "is_active": s.get("is_active", False),
            "login_method": s.get("login_method", "email"),
            "is_current": s["id"] == user.get("session_id", ""),
        }
        for s in sessions
        if s.get("is_active", False)
    ]
    return {"sessions": active, "total": len(active)}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, user: dict = Depends(get_current_user)):
    """Revoke a specific session (set is_active=False)."""
    session = get_document("sessions", session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your session")
    update_document("sessions", session_id, {"is_active": False})
    return {"message": "Session revoked"}


@router.delete("/sessions")
async def revoke_all_sessions(user: dict = Depends(get_current_user)):
    """Revoke all sessions except the current one."""
    current_session_id = user.get("session_id", "")
    sessions = query_documents("sessions", "user_id", "==", user["user_id"])
    revoked = 0
    for s in sessions:
        if s.get("is_active", False) and s["id"] != current_session_id:
            update_document("sessions", s["id"], {"is_active": False})
            revoked += 1
    return {"message": f"Revoked {revoked} session(s)", "revoked_count": revoked}


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """Log out: deactivate current session and record logout activity."""
    session_id = user.get("session_id", "")
    if session_id:
        update_document("sessions", session_id, {"is_active": False})

    # Log logout activity
    try:
        create_document("user_activities", {
            "user_id": user["user_id"],
            "action": "logout",
            "resource_type": "session",
            "resource_id": session_id,
            "details": {},
            "ip_address": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("User-Agent", ""),
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning("Failed to log logout activity: %s", e)

    return {"message": "Logged out successfully"}
