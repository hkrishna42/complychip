"""ComplyChip V3 - Webhook Routes (n8n callbacks)"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.firestore_service import update_document, get_document, create_document
from backend.services.scoring_service import calculate_entity_score, calculate_document_score

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Convert various date formats to ISO 8601 (YYYY-MM-DD).

    Handles: mm-dd-yyyy, mm/dd/yyyy, yyyy-mm-dd, ISO timestamps.
    Returns None if parsing fails.
    """
    if not date_str:
        return None
    date_str = date_str.strip()

    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]

    # mm-dd-yyyy or mm/dd/yyyy
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", date_str)
    if m:
        month, day, year = m.groups()
        try:
            return f"{year}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            return None

    return date_str


def _derive_compliance_status(score: float, expiry_date: Optional[str]) -> str:
    """Derive compliance status from score and expiry date."""
    if expiry_date:
        try:
            exp = datetime.fromisoformat(expiry_date.replace("Z", "+00:00"))
            if len(expiry_date) == 10:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return "expired"
        except (ValueError, TypeError):
            pass

    if score >= 80:
        return "compliant"
    if score >= 60:
        return "warning"
    if score >= 40:
        return "non_compliant"
    return "critical"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DocumentProcessedPayload(BaseModel):
    """Expanded payload from n8n after document processing + Gemini analysis."""
    document_id: str
    entity_id: Optional[str] = None
    status: str = "processed"

    # Gemini-extracted fields
    ai_summary: Optional[str] = None
    ai_tags: Optional[list] = None
    company_name: Optional[str] = None
    category: Optional[str] = None
    party_a: Optional[str] = None
    party_b: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    jurisdiction: Optional[str] = None
    key_clauses: Optional[list] = None
    monetary_amounts: Optional[list] = None
    compliance_requirements: Optional[list] = None
    risk_flags: Optional[list] = None
    document_name: Optional[str] = None
    document_type_detected: Optional[str] = None

    # Text extraction
    extracted_content: Optional[str] = None
    extracted_text: Optional[str] = None
    extracted_metadata: Optional[dict] = None
    page_count: Optional[int] = None

    # Pinecone indexing status
    pinecone_indexed: Optional[bool] = None

    # Error
    error: Optional[str] = None


class AnalysisCompletePayload(BaseModel):
    document_id: str
    entity_id: Optional[str] = None
    analysis_type: str = "compliance"
    results: Optional[dict] = None
    score: Optional[float] = None
    gaps: Optional[list] = None
    error: Optional[str] = None


class ReminderSentPayload(BaseModel):
    reminder_id: Optional[str] = None
    document_id: Optional[str] = None
    entity_id: Optional[str] = None
    recipient_email: str = ""
    status: str = "sent"
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/document-processed")
async def document_processed(payload: DocumentProcessedPayload):
    """n8n callback: Document has been processed (text extracted, AI analysis done).

    Writes all AI-extracted fields to Firestore, computes document score,
    derives compliance status, and recalculates the parent entity score.
    """
    now = datetime.now(timezone.utc).isoformat()

    updates: dict = {
        "processing_status": "complete" if not payload.error else "error",
        "status": "processed" if not payload.error else "processing_error",
        "processed_at": now,
        "updated_at": now,
    }

    # Error case
    if payload.error:
        updates["processing_error"] = payload.error
        try:
            update_document("documents", payload.document_id, updates)
        except Exception:
            pass
        return {
            "message": "Document processing error recorded",
            "document_id": payload.document_id,
            "status": "error",
        }

    # AI-extracted metadata
    if payload.ai_summary:
        updates["ai_summary"] = payload.ai_summary
    if payload.ai_tags:
        updates["ai_tags"] = payload.ai_tags
    if payload.company_name:
        updates["document_company_name"] = payload.company_name
    if payload.category:
        updates["category"] = payload.category
    if payload.party_a:
        updates["party_a"] = payload.party_a
    if payload.party_b:
        updates["party_b"] = payload.party_b
    if payload.jurisdiction:
        updates["jurisdiction"] = payload.jurisdiction
    if payload.key_clauses:
        updates["key_clauses"] = payload.key_clauses
    if payload.monetary_amounts:
        updates["monetary_amounts"] = payload.monetary_amounts
    if payload.compliance_requirements:
        updates["compliance_requirements"] = payload.compliance_requirements
    if payload.risk_flags:
        updates["risk_flags"] = payload.risk_flags
    if payload.document_type_detected:
        updates["document_type_detected"] = payload.document_type_detected
    if payload.document_name:
        updates["name"] = payload.document_name

    # Dates (normalize from various formats)
    if payload.effective_date:
        normalized = _normalize_date(payload.effective_date)
        if normalized:
            updates["effective_date"] = normalized
    if payload.expiry_date:
        normalized = _normalize_date(payload.expiry_date)
        if normalized:
            updates["expiry_date"] = normalized

    # Extracted text/content
    if payload.extracted_content:
        updates["extracted_content"] = payload.extracted_content
    elif payload.extracted_text:
        updates["extracted_content"] = payload.extracted_text

    if payload.extracted_metadata:
        updates["extracted_metadata"] = payload.extracted_metadata
    if payload.page_count is not None:
        updates["page_count"] = payload.page_count

    # Pinecone indexing
    if payload.pinecone_indexed is not None:
        updates["pinecone_indexed"] = payload.pinecone_indexed

    # Write all AI fields to Firestore first
    try:
        update_document("documents", payload.document_id, updates)
    except Exception as e:
        print(f"Warning: Failed to update document {payload.document_id}: {e}")

    # Now compute document score from the updated document
    doc_score = 0
    try:
        doc = get_document("documents", payload.document_id)
        if doc:
            score_result = calculate_document_score(doc)
            doc_score = score_result.get("score", 0)
            expiry = doc.get("expiry_date", updates.get("expiry_date"))
            compliance_status = _derive_compliance_status(doc_score, expiry)
            update_document("documents", payload.document_id, {
                "score": doc_score,
                "compliance_status": compliance_status,
            })
    except Exception as e:
        print(f"Warning: Score computation failed for {payload.document_id}: {e}")

    # Recalculate entity score
    entity_id = payload.entity_id
    entity_score = None
    if not entity_id:
        # Try to get entity_id from the document itself
        try:
            doc = get_document("documents", payload.document_id)
            if doc:
                entity_id = doc.get("entity_id", "")
        except Exception:
            pass

    if entity_id:
        try:
            entity_score = calculate_entity_score(entity_id)
            update_document("entities", entity_id, {
                "compliance_score": entity_score.get("overall_score", 0),
                "risk_level": entity_score.get("risk_level", "unknown"),
                "updated_at": now,
            })
        except Exception as e:
            print(f"Warning: Entity score update failed for {entity_id}: {e}")

    return {
        "message": "Document processing complete",
        "document_id": payload.document_id,
        "entity_id": entity_id,
        "document_score": doc_score,
        "entity_score": entity_score.get("overall_score") if entity_score else None,
        "status": "processed",
    }


@router.post("/analysis-complete")
async def analysis_complete(payload: AnalysisCompletePayload):
    """n8n callback: Compliance analysis is complete.

    Stores analysis results and optionally recalculates entity score.
    """
    # Store analysis results on the document
    updates = {
        "analysis_status": "complete",
        "analysis_type": payload.analysis_type,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.results:
        updates["analysis_results"] = payload.results
    if payload.score is not None:
        updates["compliance_score"] = payload.score
    if payload.gaps:
        updates["compliance_gaps"] = payload.gaps
    if payload.error:
        updates["analysis_status"] = "error"
        updates["analysis_error"] = payload.error

    try:
        update_document("documents", payload.document_id, updates)
    except Exception:
        pass

    # Recalculate entity score if entity_id provided
    entity_score = None
    if payload.entity_id:
        try:
            entity_score = calculate_entity_score(payload.entity_id)
            update_document("entities", payload.entity_id, {
                "compliance_score": entity_score.get("overall_score", 0),
                "risk_level": entity_score.get("risk_level", "unknown"),
            })
        except Exception:
            pass

    return {
        "message": "Analysis results stored",
        "document_id": payload.document_id,
        "entity_id": payload.entity_id,
        "entity_score": entity_score.get("overall_score") if entity_score else None,
    }


@router.post("/reminder-sent")
async def reminder_sent(payload: ReminderSentPayload):
    """n8n callback: Reminder email has been sent.

    Logs the reminder status in Firestore.
    """
    log_data = {
        "reminder_id": payload.reminder_id or "",
        "document_id": payload.document_id or "",
        "entity_id": payload.entity_id or "",
        "recipient_email": payload.recipient_email,
        "status": payload.status,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.error:
        log_data["error"] = payload.error
        log_data["status"] = "error"

    try:
        create_document("reminder_log", log_data)
    except Exception:
        pass

    return {
        "message": "Reminder status logged",
        "status": log_data["status"],
        "recipient_email": payload.recipient_email,
    }
