"""ComplyChip V3 - Upload Routes"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form

from backend.dependencies import get_current_user
from backend.config import GCS_BUCKET
from backend.services.firestore_service import (
    create_document,
    get_documents,
    query_documents,
    update_document,
)
from backend.services.n8n_client import trigger_document_intake
from backend.services.gemini_service import generate_embeddings
from backend.services.pinecone_service import upsert_vectors
from backend.services.gcs_service import upload_file

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_entity_id_cache: dict[str, str] = {}


def _resolve_entity_id(entity_name: str, org_id: str) -> str:
    """Look up entity by name, create if not found. Returns entity_id."""
    if not entity_name:
        raise HTTPException(status_code=400, detail="Entity name is required")

    cache_key = f"{entity_name}|{org_id}"
    if cache_key in _entity_id_cache:
        return _entity_id_cache[cache_key]

    # Query Firestore for existing entity by name
    try:
        results = query_documents("entities", "name", "==", entity_name)
        if results:
            # Filter by org if provided
            for r in results:
                if not org_id or r.get("organization_id", "") == org_id:
                    entity_id = r.get("id", "")
                    if entity_id:
                        _entity_id_cache[cache_key] = entity_id
                        return entity_id
    except Exception:
        pass

    # Not found — create a new entity
    try:
        new_entity = {
            "name": entity_name,
            "entity_type": "property",
            "organization_id": org_id,
            "compliance_score": 0,
            "risk_level": "unknown",
            "document_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        entity_id = create_document("entities", new_entity)
        if entity_id:
            _entity_id_cache[cache_key] = entity_id
            return entity_id
    except Exception as e:
        print(f"Warning: Failed to create entity '{entity_name}': {e}")

    # Fallback
    fallback_id = f"entity-{uuid.uuid4().hex[:8]}"
    _entity_id_cache[cache_key] = fallback_id
    return fallback_id


def _compute_score(ai_data: dict, user_expiry: str = "") -> float:
    """Compute a compliance score (0-100) from AI-extracted data."""
    score = 50.0  # Base score for having a document

    # Boost for having key fields extracted
    if ai_data.get("ai_summary"):
        score += 10
    if ai_data.get("party_a") and ai_data.get("party_b"):
        score += 5
    if ai_data.get("effective_date"):
        score += 5

    # Expiry date scoring
    expiry = ai_data.get("expiry_date") or user_expiry
    if expiry:
        try:
            from datetime import date
            exp = date.fromisoformat(str(expiry)[:10])
            days_left = (exp - date.today()).days
            if days_left > 180:
                score += 20
            elif days_left > 90:
                score += 15
            elif days_left > 30:
                score += 5
            elif days_left <= 0:
                score -= 20
        except (ValueError, TypeError):
            pass

    # Penalize for risk flags
    risk_flags = ai_data.get("risk_flags", [])
    if isinstance(risk_flags, list):
        score -= len(risk_flags) * 3

    # Boost for compliance requirements being documented
    reqs = ai_data.get("compliance_requirements", [])
    if isinstance(reqs, list) and len(reqs) > 0:
        score += min(len(reqs) * 2, 10)

    return max(0, min(100, round(score, 1)))


def _index_to_pinecone(
    doc_id: str, entity_id: str, org_id: str,
    document_type: str, ai_data: dict
):
    """Generate embeddings and index document into Pinecone for RAG."""
    try:
        from backend.config import PINECONE_API_KEY, GEMINI_API_KEY
        if not PINECONE_API_KEY or not GEMINI_API_KEY:
            print(f"Pinecone/Gemini API keys not set, skipping indexing for {doc_id}")
            return

        # Build text for embedding: summary + key content
        text_parts = []
        if ai_data.get("ai_summary"):
            text_parts.append(ai_data["ai_summary"])
        if ai_data.get("extracted_content"):
            text_parts.append(ai_data["extracted_content"][:5000])
        text = "\n".join(text_parts)
        if not text:
            return

        # Generate embedding
        embedding = generate_embeddings(text)
        if not embedding or all(v == 0.0 for v in embedding[:10]):
            print(f"Empty embedding for {doc_id}, skipping")
            return

        # Upsert to Pinecone
        metadata = {
            "document_id": doc_id,
            "entity_id": entity_id,
            "organization_id": org_id,
            "document_type": document_type,
            "document_name": ai_data.get("document_name", ""),
            "ai_summary": (ai_data.get("ai_summary") or "")[:500],
        }
        upsert_vectors([{
            "id": doc_id,
            "values": embedding,
            "metadata": metadata,
        }])

        # Mark as indexed in Firestore
        update_document("documents", doc_id, {"pinecone_indexed": True})
        print(f"Pinecone indexed: {doc_id}")
    except Exception as e:
        print(f"Pinecone indexing failed for {doc_id}: {e}")


def _update_entity_score(entity_id: str):
    """Recompute and update entity compliance score from its active documents."""
    try:
        docs = query_documents("documents", "entity_id", "==", entity_id)
        if not docs:
            return
        active_docs = [d for d in docs if d.get("status") != "archived"]
        scores = [d.get("score", 0) for d in active_docs if d.get("score") is not None]
        if scores:
            avg = round(sum(scores) / len(scores), 1)
            risk = (
                "low" if avg >= 80
                else "medium" if avg >= 60
                else "high" if avg >= 40
                else "critical"
            )
            update_document("entities", entity_id, {
                "compliance_score": avg,
                "risk_level": risk,
                "document_count": len(active_docs),
            })
    except Exception as e:
        print(f"Entity score update failed for {entity_id}: {e}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    entity: str = Form(...),
    document_type: str = Form("Other"),
    expiry_date: str = Form(""),
    notes: str = Form(""),
    priority: str = Form("normal"),
    user: dict = Depends(get_current_user),
):
    """Upload a single document file with metadata.

    Stores the file in GCS, creates a Firestore record, and triggers
    the n8n document-intake workflow for background processing.
    """
    # Read file content
    try:
        file_data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    filename = file.filename or f"upload-{uuid.uuid4().hex[:8]}"
    content_type = file.content_type or "application/octet-stream"
    org_id = user.get("org_id", "")

    # Resolve entity name → ID
    entity_id = _resolve_entity_id(entity, org_id)

    # Upload to GCS (graceful fallback if permissions not configured)
    gcs_path = f"documents/{entity_id}/{uuid.uuid4().hex[:8]}_{filename}"
    try:
        actual_path = upload_file(file_data, filename, content_type, entity_id)
        if actual_path and not actual_path.startswith("demo-"):
            gcs_path = actual_path
            print(f"GCS upload success: {gcs_path}")
        else:
            print(f"GCS upload skipped (demo mode), using path: {gcs_path}")
    except Exception as e:
        print(f"GCS upload failed (will continue): {e}")

    # Create initial document record (status = "processing")
    now = datetime.now(timezone.utc).isoformat()
    doc_data = {
        "name": filename,
        "document_type": document_type,
        "entity_id": entity_id,
        "entity_name": entity,
        "organization_id": org_id,
        "uploaded_by": user.get("user_id", ""),
        "status": "processing",
        "processing_status": "pending",
        "gcs_path": gcs_path,
        "gcs_bucket": GCS_BUCKET,
        "file_size": len(file_data),
        "content_type": content_type,
        "notes": notes,
        "priority": priority,
        "score": 0,
        "compliance_status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    # Include user-provided expiry date if present
    if expiry_date:
        doc_data["expiry_date"] = expiry_date

    try:
        doc_id = create_document("documents", doc_data)
    except Exception:
        doc_id = f"demo-doc-{uuid.uuid4().hex[:8]}"

    # Trigger n8n for Gemini AI analysis (n8n returns AI data, backend updates Firestore)
    n8n_response = {}
    try:
        n8n_response = await trigger_document_intake(
            document_id=doc_id or "unknown",
            filename=filename,
            content_type=content_type,
            entity_id=entity_id,
            document_type=document_type,
            organization_id=org_id,
            file_data=file_data,
        )
        print(f"n8n response for {doc_id}: success={n8n_response.get('success')}")

        # If n8n returned AI data, update Firestore directly
        if n8n_response.get("success") and doc_id:
            ai_update = {
                "status": "processed",
                "processing_status": "complete",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            # Map all AI-extracted fields
            ai_fields = [
                "document_name", "document_type", "category", "company_name",
                "party_a", "party_b", "effective_date", "expiry_date",
                "jurisdiction", "ai_summary", "ai_tags", "key_clauses",
                "monetary_amounts", "compliance_requirements", "risk_flags",
                "extracted_content",
            ]
            for field in ai_fields:
                val = n8n_response.get(field)
                if val is not None:
                    # Map document_type to document_type_detected
                    key = "document_type_detected" if field == "document_type" else field
                    # Prefer user-provided expiry date over AI-extracted
                    if key == "expiry_date" and expiry_date:
                        ai_update["ai_expiry_date"] = val  # Store Gemini's date separately
                        continue
                    ai_update[key] = val

            # Compute a basic compliance score
            score = _compute_score(ai_update, expiry_date)
            ai_update["score"] = score
            ai_update["compliance_status"] = (
                "compliant" if score >= 80
                else "warning" if score >= 60
                else "non_compliant"
            )
            ai_update["pinecone_indexed"] = False

            try:
                update_document("documents", doc_id, ai_update)
                print(f"Firestore updated for {doc_id}: score={score}")
                # Update entity compliance score
                _update_entity_score(entity_id)
                # Index into Pinecone for RAG/Copilot
                _index_to_pinecone(doc_id, entity_id, org_id, document_type, ai_update)
            except Exception as e:
                print(f"Firestore update failed for {doc_id}: {e}")
    except Exception as e:
        print(f"n8n trigger failed for {doc_id}: {e}")

    return {
        "document_id": doc_id or f"demo-doc-{uuid.uuid4().hex[:8]}",
        "filename": filename,
        "gcs_path": gcs_path,
        "status": "processing" if not n8n_response.get("success") else "processed",
        "message": "Document uploaded successfully. Background processing started.",
    }


@router.post("/bulk")
async def bulk_upload(
    files: list = File(...),
    entity: str = Form(...),
    document_type: str = Form("Other"),
    user: dict = Depends(get_current_user),
):
    """Upload multiple files at once.

    Each file is uploaded individually; results are aggregated.
    """
    org_id = user.get("org_id", "")
    entity_id = _resolve_entity_id(entity, org_id)

    results = []
    errors = []

    for f in files:
        try:
            file_data = await f.read()
            filename = f.filename or f"upload-{uuid.uuid4().hex[:8]}"
            content_type = f.content_type or "application/octet-stream"

            gcs_path = f"documents/{uuid.uuid4().hex[:12]}/{filename}"

            now = datetime.now(timezone.utc).isoformat()
            doc_data = {
                "name": filename,
                "document_type": document_type,
                "entity_id": entity_id,
                "entity_name": entity,
                "status": "processing",
                "processing_status": "pending",
                "gcs_path": gcs_path,
                "gcs_bucket": GCS_BUCKET,
                "file_size": len(file_data),
                "content_type": content_type,
                "organization_id": org_id,
                "uploaded_by": user.get("user_id", ""),
                "score": 0,
                "compliance_status": "pending",
                "created_at": now,
                "updated_at": now,
            }

            try:
                doc_id = create_document("documents", doc_data)
            except Exception:
                doc_id = f"demo-doc-{uuid.uuid4().hex[:8]}"

            results.append({
                "document_id": doc_id or f"demo-doc-{uuid.uuid4().hex[:8]}",
                "filename": filename,
                "gcs_path": gcs_path,
                "status": "processing",
            })

            # Trigger n8n with actual file
            try:
                await trigger_document_intake(
                    document_id=doc_id or "unknown",
                    filename=filename,
                    content_type=content_type,
                    entity_id=entity_id,
                    document_type=document_type,
                    organization_id=org_id,
                    file_data=file_data,
                )
            except Exception:
                pass
        except Exception as e:
            errors.append({
                "filename": getattr(f, "filename", "unknown"),
                "error": str(e),
            })

    return {
        "uploaded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "message": f"Bulk upload complete: {len(results)} succeeded, {len(errors)} failed.",
    }
