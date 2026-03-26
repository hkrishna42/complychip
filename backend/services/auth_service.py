"""ComplyChip V3 - Authentication Service"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from passlib.context import CryptContext
from jose import jwt, JWTError

from backend.config import (
    JWT_SECRET, JWT_REFRESH_SECRET, JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token_pair(user_id: str, role: str, email: str, org_id: str = "",
                      session_id: str = "") -> dict:
    """Create JWT access + refresh token pair.

    Args:
        session_id: Optional session document ID to embed in tokens.
    """
    now = datetime.now(timezone.utc)
    jti = str(uuid4())
    access_payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "org": org_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if session_id:
        access_payload["sid"] = session_id
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    if session_id:
        refresh_payload["sid"] = session_id
    return {
        "access_token": jwt.encode(access_payload, JWT_SECRET, algorithm=JWT_ALGORITHM),
        "refresh_token": jwt.encode(refresh_payload, JWT_REFRESH_SECRET, algorithm=JWT_ALGORITHM),
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "token_jti": jti,
    }


def verify_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return {
            "user_id": payload["sub"],
            "role": payload.get("role", "viewer"),
            "email": payload.get("email", ""),
            "org_id": payload.get("org", ""),
            "session_id": payload.get("sid", ""),
        }
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")


def verify_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_REFRESH_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        return {
            "user_id": payload["sub"],
            "jti": payload.get("jti", ""),
            "session_id": payload.get("sid", ""),
        }
    except JWTError as e:
        raise ValueError(f"Invalid refresh token: {e}")
