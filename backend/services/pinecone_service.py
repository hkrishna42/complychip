"""ComplyChip V3 - Pinecone Vector Database Service"""
from __future__ import annotations

from typing import Optional

from backend.config import PINECONE_API_KEY, PINECONE_INDEX

_index = None


def _init_pinecone():
    """Lazily initialize the Pinecone client and index."""
    global _index
    if _index is not None:
        return True
    if not PINECONE_API_KEY:
        return False
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _index = pc.Index(PINECONE_INDEX)
        return True
    except Exception as e:
        print(f"Warning: Pinecone initialization failed: {e}")
        return False


def upsert_vectors(vectors: list) -> int:
    """Upsert vectors into Pinecone.

    vectors: list of dicts with 'id', 'values', and optional 'metadata'.
    Returns count of upserted vectors.
    Falls back to returning the input count when Pinecone is not configured.
    """
    if not _init_pinecone():
        return len(vectors)  # demo fallback

    try:
        formatted = []
        for v in vectors:
            item = {
                "id": v["id"],
                "values": v["values"],
            }
            if "metadata" in v:
                item["metadata"] = v["metadata"]
            formatted.append(item)
        response = _index.upsert(vectors=formatted)
        return response.get("upserted_count", len(vectors))
    except Exception as e:
        print(f"Warning: Pinecone upsert failed: {e}")
        return len(vectors)


def query_similar(
    vector: list,
    top_k: int = 5,
    filter_metadata: Optional[dict] = None,
) -> list:
    """Query Pinecone for similar vectors.

    Returns a list of match dicts with 'id', 'score', and 'metadata'.
    Falls back to empty results when Pinecone is not configured.
    """
    if not _init_pinecone():
        return []  # demo fallback

    try:
        kwargs = {
            "vector": vector,
            "top_k": top_k,
            "include_metadata": True,
        }
        if filter_metadata:
            kwargs["filter"] = filter_metadata
        response = _index.query(**kwargs)
        matches = []
        for m in response.get("matches", []):
            matches.append({
                "id": m["id"],
                "score": m["score"],
                "metadata": m.get("metadata", {}),
            })
        return matches
    except Exception as e:
        print(f"Warning: Pinecone query failed: {e}")
        return []


def delete_vectors(ids: list) -> bool:
    """Delete vectors by their IDs.

    Returns True on success.
    Falls back to True when Pinecone is not configured.
    """
    if not _init_pinecone():
        return True  # demo fallback

    try:
        _index.delete(ids=ids)
        return True
    except Exception as e:
        print(f"Warning: Pinecone delete failed: {e}")
        return False


def fetch_vectors(ids: list) -> dict:
    """Fetch vectors by IDs.

    Returns a dict mapping id -> vector data.
    """
    if not _init_pinecone():
        return {}

    try:
        response = _index.fetch(ids=ids)
        return {
            vid: {
                "id": vid,
                "values": vdata.get("values", []),
                "metadata": vdata.get("metadata", {}),
            }
            for vid, vdata in response.get("vectors", {}).items()
        }
    except Exception as e:
        print(f"Warning: Pinecone fetch failed: {e}")
        return {}


def describe_index_stats() -> dict:
    """Get index statistics.

    Returns dict with total vector count and namespace info.
    """
    if not _init_pinecone():
        return {"total_vector_count": 0, "namespaces": {}}

    try:
        stats = _index.describe_index_stats()
        return {
            "total_vector_count": stats.get("total_vector_count", 0),
            "namespaces": stats.get("namespaces", {}),
        }
    except Exception as e:
        print(f"Warning: Pinecone stats failed: {e}")
        return {"total_vector_count": 0, "namespaces": {}}
