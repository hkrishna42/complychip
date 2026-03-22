"""ComplyChip V3 - Rate Limiting Middleware

Uses slowapi to enforce per-endpoint rate limits based on client IP.
"""
from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Limiter instance (keyed by client IP)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Predefined rate-limit strings for different endpoint categories
# ---------------------------------------------------------------------------
auth_limit: str = "5/minute"
ai_limit: str = "30/minute"
upload_limit: str = "10/minute"
read_limit: str = "100/minute"


def setup_rate_limiter(app: FastAPI) -> None:
    """Attach the slowapi limiter to a FastAPI application.

    This adds the limiter to ``app.state`` (required by slowapi) and
    registers the custom 429 exception handler.

    Parameters
    ----------
    app:
        The FastAPI application instance.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
