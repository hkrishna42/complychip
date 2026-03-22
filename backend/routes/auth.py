"""ComplyChip V3 - Authentication Routes"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.services.auth_service import (
    hash_password, verify_password, create_token_pair, verify_refresh_token,
)
from backend.services.firestore_service import (
    get_user_by_email, create_document, get_document, update_document,
)
from backend.dependencies import get_current_user, require_roles

router = APIRouter()


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


# --- Demo mode fallback (when Firestore is unavailable) ---
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


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate user and return JWT token pair."""
    # Try Firestore first
    user = get_user_by_email(body.email)

    if user:
        stored_pw = user.get("password_hash") or user.get("password", "")
        if not stored_pw or not verify_password(body.password, stored_pw):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        tokens = create_token_pair(
            user_id=user["id"],
            role=user.get("role", "viewer"),
            email=user["email"],
            org_id=user.get("organization_id", ""),
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
    user = get_document("users", payload["user_id"])
    if not user:
        # Demo fallback
        for demo in DEMO_USERS.values():
            if demo["id"] == payload["user_id"]:
                tokens = create_token_pair(demo["id"], demo["role"], demo["email"], demo["organization_id"])
                return {**tokens, "token_type": "bearer"}
        raise HTTPException(status_code=401, detail="User not found")
    tokens = create_token_pair(user["id"], user.get("role", "viewer"), user["email"], user.get("organization_id", ""))
    return {**tokens, "token_type": "bearer"}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user profile."""
    full_user = get_document("users", user["user_id"])
    if full_user:
        return {
            "id": full_user["id"],
            "email": full_user["email"],
            "name": full_user.get("name", ""),
            "role": full_user.get("role", "viewer"),
            "organization_id": full_user.get("organization_id", ""),
            "preferences": full_user.get("preferences", {}),
        }
    # Demo fallback
    return {
        "id": user["user_id"],
        "email": user["email"],
        "name": "Admin User",
        "role": user["role"],
        "organization_id": user.get("org_id", ""),
        "preferences": {"dark_mode": False},
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
