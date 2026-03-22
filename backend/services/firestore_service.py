"""ComplyChip V3 - Firestore Service"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from backend.config import get_firestore_client


def _serialize(data: dict) -> dict:
    """Convert Firestore Timestamp/datetime values to ISO strings for JSON."""
    for key, val in data.items():
        if hasattr(val, "isoformat"):
            data[key] = val.isoformat()
        elif isinstance(val, dict):
            data[key] = _serialize(val)
    return data


def get_document(collection: str, doc_id: str) -> Optional[dict]:
    db = get_firestore_client()
    if not db:
        return None
    doc = db.collection(collection).document(doc_id).get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return _serialize(data)
    return None


def get_documents(collection: str, filters: list = None, order_by: str = None,
                  limit: int = None, direction: str = "ASCENDING") -> list:
    db = get_firestore_client()
    if not db:
        return []
    query = db.collection(collection)
    if filters:
        for field, op, value in filters:
            query = query.where(field, op, value)
    if order_by:
        from google.cloud.firestore_v1 import query as fquery
        dir_val = fquery.Query.DESCENDING if direction == "DESCENDING" else fquery.Query.ASCENDING
        query = query.order_by(order_by, direction=dir_val)
    if limit:
        query = query.limit(limit)
    docs = query.stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        results.append(_serialize(data))
    return results


def create_document(collection: str, data: dict, doc_id: str = None) -> str:
    db = get_firestore_client()
    if not db:
        return ""
    data["created_at"] = datetime.now(timezone.utc)
    data["updated_at"] = datetime.now(timezone.utc)
    if doc_id:
        db.collection(collection).document(doc_id).set(data)
        return doc_id
    else:
        doc_ref = db.collection(collection).add(data)
        return doc_ref[1].id


def update_document(collection: str, doc_id: str, data: dict) -> bool:
    db = get_firestore_client()
    if not db:
        return False
    data["updated_at"] = datetime.now(timezone.utc)
    db.collection(collection).document(doc_id).update(data)
    return True


def delete_document(collection: str, doc_id: str) -> bool:
    db = get_firestore_client()
    if not db:
        return False
    db.collection(collection).document(doc_id).delete()
    return True


def query_documents(collection: str, field: str, op: str, value) -> list:
    return get_documents(collection, filters=[(field, op, value)])


# --- Typed accessors ---

def get_user_by_email(email: str) -> Optional[dict]:
    results = query_documents("users", "email", "==", email)
    return results[0] if results else None


def get_entity_documents(entity_id: str) -> list:
    return query_documents("documents", "entity_id", "==", entity_id)


def get_organization_rules(org_id: str) -> list:
    return get_documents("compliance_rules",
                         filters=[("organization_id", "==", org_id), ("is_active", "==", True)])


def get_vendor_documents(vendor_name: str, org_id: str) -> list:
    return get_documents("documents",
                         filters=[("document_company_name", "==", vendor_name),
                                  ("organization_id", "==", org_id)])
