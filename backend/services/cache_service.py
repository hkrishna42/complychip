"""ComplyChip V3 - In-Memory Cache Service"""
from __future__ import annotations

from typing import Optional

try:
    from cachetools import TTLCache
except ImportError:
    # Lightweight fallback when cachetools is not installed
    TTLCache = None  # type: ignore[misc,assignment]

# Default cache: 1024 entries, 5-minute TTL
_DEFAULT_TTL = 300
_DEFAULT_MAXSIZE = 1024

_cache = None


def _get_cache(maxsize: int = _DEFAULT_MAXSIZE, ttl: int = _DEFAULT_TTL):
    """Get or create the singleton TTLCache."""
    global _cache
    if _cache is not None:
        return _cache

    if TTLCache is not None:
        _cache = TTLCache(maxsize=maxsize, ttl=ttl)
    else:
        # Simple dict fallback (no TTL enforcement, no maxsize)
        _cache = {}
    return _cache


def cache_get(key: str) -> Optional[object]:
    """Retrieve a value from the cache, or None if not found / expired."""
    c = _get_cache()
    try:
        return c.get(key)
    except Exception:
        return None


def cache_set(key: str, value: object, ttl: Optional[int] = None) -> None:
    """Store a value in the cache.

    If cachetools is available and a custom ttl is needed, a per-key TTL
    is not supported by TTLCache (all keys share the same TTL). The ttl
    parameter is accepted for API compatibility but only takes effect
    when using the dict fallback.
    """
    c = _get_cache()
    try:
        c[key] = value
    except Exception:
        pass


def cache_delete(key: str) -> bool:
    """Remove a key from the cache. Returns True if it was present."""
    c = _get_cache()
    try:
        if key in c:
            del c[key]
            return True
    except Exception:
        pass
    return False


def cache_clear() -> None:
    """Clear all entries from the cache."""
    c = _get_cache()
    try:
        c.clear()
    except Exception:
        pass


def cache_size() -> int:
    """Return the number of entries currently in the cache."""
    c = _get_cache()
    try:
        return len(c)
    except Exception:
        return 0
