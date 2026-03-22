"""ComplyChip V3 - AI Copilot Routes"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.gemini_service import (
    chat_completion,
    extract_metadata,
    analyze_compliance_gaps,
    generate_embeddings,
)
from backend.services.pinecone_service import query_similar
from backend.services.firestore_service import get_document, get_entity_documents
from backend.services.scoring_service import get_score_breakdown

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CopilotQuery(BaseModel):
    query: str
    entity_id: Optional[str] = None
    conversation_history: Optional[list] = None


class AnalyzeRequest(BaseModel):
    document_id: str
    analysis_type: str = "full"  # full, clauses, metadata, compliance


class SuggestionRequest(BaseModel):
    entity_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/query")
async def copilot_query(body: CopilotQuery, user: dict = Depends(get_current_user)):
    """RAG-powered compliance query.

    1. Generates embedding for the query
    2. Retrieves relevant document chunks from Pinecone
    3. Sends query + context to Gemini for response
    """
    query_text = body.query
    if not query_text.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Build conversation messages
    messages = []
    if body.conversation_history:
        for msg in body.conversation_history[-10:]:  # cap history
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
    messages.append({"role": "user", "content": query_text})

    # RAG: embed query and search for relevant documents
    context_docs = []
    try:
        embedding = generate_embeddings(query_text)
        filter_meta = {}
        org_id = user.get("org_id", "")
        if org_id:
            filter_meta["organization_id"] = org_id
        if body.entity_id:
            filter_meta["entity_id"] = body.entity_id

        matches = query_similar(
            vector=embedding,
            top_k=5,
            filter_metadata=filter_meta if filter_meta else None,
        )
        for m in matches:
            context_docs.append({
                "name": m.get("metadata", {}).get("name", "Document"),
                "text": m.get("metadata", {}).get("text", ""),
                "score": m.get("score", 0),
            })
    except Exception:
        pass

    # If no Pinecone results, try fetching entity docs directly
    if not context_docs and body.entity_id:
        try:
            entity_docs = get_entity_documents(body.entity_id)
            for d in entity_docs[:5]:
                context_docs.append({
                    "name": d.get("name", "Document"),
                    "text": d.get("extracted_text", d.get("notes", "")),
                })
        except Exception:
            pass

    # Generate response
    response = chat_completion(messages, context_docs if context_docs else None)

    return {
        "response": response,
        "sources": [
            {"name": d["name"], "relevance": d.get("score", 0)}
            for d in context_docs[:5]
        ],
        "query": query_text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/analyze")
async def analyze_document(body: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """Analyze a specific document using AI.

    Supports different analysis types: full, clauses, metadata, compliance.
    """
    doc = None
    try:
        doc = get_document("documents", body.document_id)
    except Exception:
        pass

    if not doc:
        # Demo fallback
        doc = {
            "id": body.document_id,
            "name": "Sample Compliance Document",
            "document_type": "Vendor Agreement",
            "extracted_text": "This is a sample vendor agreement between Acme Corp and ComplyChip Inc.",
        }

    text = doc.get("extracted_text", doc.get("notes", "Sample document text."))
    doc_type = doc.get("document_type", "unknown")

    result = {"document_id": body.document_id, "analysis_type": body.analysis_type}

    if body.analysis_type in ("full", "metadata"):
        result["metadata"] = extract_metadata(text, doc_type)

    if body.analysis_type in ("full", "compliance"):
        result["gaps"] = analyze_compliance_gaps(
            doc_data={"text": text, "type": doc_type, "name": doc.get("name", "")},
            rules=[
                {"id": "R1", "name": "Document Validity", "requirement": "Must have valid expiry date"},
                {"id": "R2", "name": "Party Identification", "requirement": "All parties must be clearly identified"},
                {"id": "R3", "name": "Jurisdiction Specified", "requirement": "Governing law must be stated"},
            ],
        )

    if body.analysis_type in ("full", "clauses"):
        metadata = result.get("metadata") or extract_metadata(text, doc_type)
        result["clauses"] = metadata.get("clauses", [])

    result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    return result


@router.post("/suggestions")
async def get_suggestions(body: SuggestionRequest, user: dict = Depends(get_current_user)):
    """Get AI-powered compliance suggestions for an entity.

    Analyzes the entity's score breakdown and documents to provide
    actionable recommendations.
    """
    entity_id = body.entity_id

    # Get score breakdown
    breakdown = get_score_breakdown(entity_id)

    # Build suggestions from recommendations in breakdown
    suggestions = []
    for rec in breakdown.get("recommendations", []):
        suggestions.append({
            "priority": rec.get("priority", "medium"),
            "category": rec.get("category", "general"),
            "suggestion": rec.get("message", ""),
            "impact": "Improves overall compliance score",
        })

    # Add AI-generated suggestions if available
    if not suggestions:
        suggestions = _demo_suggestions(entity_id)

    return {
        "entity_id": entity_id,
        "current_score": breakdown.get("overall_score", 0),
        "current_grade": breakdown.get("grade", "N/A"),
        "suggestions": suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _demo_suggestions(entity_id: str) -> list:
    return [
        {
            "priority": "critical",
            "category": "expiry",
            "suggestion": "Renew expired insurance certificates to restore coverage and avoid liability gaps.",
            "impact": "Could improve score by 15-20 points",
        },
        {
            "priority": "high",
            "category": "completeness",
            "suggestion": "Upload missing Environmental Permit to achieve full document coverage.",
            "impact": "Could improve completeness score by 16%",
        },
        {
            "priority": "medium",
            "category": "vendor_risk",
            "suggestion": "Request updated W-9 and insurance certificates from high-risk vendors.",
            "impact": "Reduces vendor risk exposure score",
        },
        {
            "priority": "low",
            "category": "compliance",
            "suggestion": "Schedule quarterly compliance review meetings with property managers.",
            "impact": "Proactive risk management and early issue detection",
        },
    ]
