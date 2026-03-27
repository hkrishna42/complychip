"""ComplyChip V3 - AI Copilot Agent Routes

Full agent system with tool-calling pattern:
1. User sends a message
2. Backend classifies intent via Gemini and extracts parameters
3. Backend executes the appropriate tool/function
4. Backend formats the result into a natural language response
5. Returns response + structured data (charts, tables, cards)

Backward-compatible: old /query, /analyze, /suggestions endpoints still work.
New endpoints: /chat, /conversations, /conversations/{id}, etc.
"""
from __future__ import annotations

import json
import re
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi import UploadFile, File, Form
from pydantic import BaseModel

from backend.dependencies import get_current_user
from backend.services.firestore_service import (
    get_document,
    get_documents,
    create_document,
    update_document,
    delete_document,
    query_documents,
    get_entity_documents,
)
from backend.services.gemini_service import (
    chat_completion,
    extract_metadata,
    analyze_compliance_gaps,
    generate_embeddings,
)
from backend.services.pinecone_service import query_similar
from backend.services.n8n_client import trigger_copilot_agent, trigger_document_intake, trigger_risk_analysis
from backend.services.scoring_service import (
    get_score_breakdown,
    calculate_entity_score,
    calculate_document_score,
)

router = APIRouter()

# Maximum messages stored per conversation
MAX_CONVERSATION_MESSAGES = 50
# Firestore collection for conversations
CONVERSATIONS_COLLECTION = "copilot_conversations"
MEMORY_COLLECTION = "copilot_memory"
MAX_MEMORIES_PER_USER = 200


# ---------------------------------------------------------------------------
# Request / Response models
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


class CopilotMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    data: Optional[dict] = None
    sources: Optional[list] = None
    timestamp: Optional[str] = None


class CopilotRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    context: Optional[dict] = {}


class CopilotResponse(BaseModel):
    message: str
    data: Optional[dict] = None
    sources: Optional[list] = []
    conversation_id: str
    suggested_actions: Optional[list] = []


class ConversationTitleRequest(BaseModel):
    title: str


# ===================================================================
# MEMORY SYSTEM
# ===================================================================

async def _extract_memories(message: str, response_text: str, user_id: str, conversation_id: str):
    """Extract key facts from a conversation turn and store as long-term memories."""
    try:
        extraction_prompt = [
            {"role": "user", "content": f"""Analyze this conversation exchange and extract 0-3 key facts worth remembering for future conversations.

User message: {message}
AI response: {response_text[:1000]}

Return a JSON array of objects with "memory_type" (one of: "fact", "preference", "entity_context") and "content" (the fact to remember).
Only include genuinely useful long-term facts. Return [] if nothing worth remembering.
Examples of good memories:
- {{"memory_type": "preference", "content": "User prefers seeing compliance scores as percentages"}}
- {{"memory_type": "entity_context", "content": "Amber Corp has 3 MSA documents with scores between 86-91"}}
- {{"memory_type": "fact", "content": "User is responsible for Q2 compliance audit"}}

Return ONLY the JSON array, nothing else."""}
        ]
        result = chat_completion(extraction_prompt, [])

        # Parse JSON from result
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1] if "\n" in result else result[3:]
            result = result.rsplit("```", 1)[0]

        memories = json.loads(result)
        if not isinstance(memories, list):
            return

        # Check current count
        existing = get_documents(MEMORY_COLLECTION,
            filters=[("user_id", "==", user_id)], limit=MAX_MEMORIES_PER_USER + 10)

        # If at limit, delete oldest
        if len(existing) >= MAX_MEMORIES_PER_USER:
            oldest = sorted(existing, key=lambda x: x.get("created_at", ""))
            for old in oldest[:len(memories)]:
                try:
                    delete_document(MEMORY_COLLECTION, old["id"])
                except Exception:
                    pass

        for mem in memories[:3]:
            if mem.get("content") and mem.get("memory_type") in ("fact", "preference", "entity_context"):
                create_document(MEMORY_COLLECTION, {
                    "user_id": user_id,
                    "memory_type": mem["memory_type"],
                    "content": mem["content"],
                    "source_conversation_id": conversation_id,
                })
    except Exception as e:
        logger.warning(f"Memory extraction failed: {e}")


def _get_relevant_memories(user_id: str, message: str, limit: int = 10) -> list:
    """Retrieve relevant memories for the current message."""
    try:
        all_memories = get_documents(MEMORY_COLLECTION,
            filters=[("user_id", "==", user_id)],
            limit=50)

        if not all_memories:
            return []

        # Simple keyword relevance scoring
        msg_words = set(message.lower().split())
        scored = []
        for mem in all_memories:
            content_words = set(mem.get("content", "").lower().split())
            overlap = len(msg_words & content_words)
            # Boost entity_context and preference types
            type_boost = 1.5 if mem.get("memory_type") == "entity_context" else (1.2 if mem.get("memory_type") == "preference" else 1.0)
            scored.append((mem, overlap * type_boost))

        # Sort by relevance, return top matches (include all if few)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, s in scored[:limit]]
    except Exception as e:
        logger.warning(f"Memory retrieval failed: {e}")
        return []


# ===================================================================
# AGENT TOOL SYSTEM
# ===================================================================

async def tool_search_documents(params: dict, user: dict) -> dict:
    """Search documents in Firestore by name, type, entity, or content."""
    query_text = params.get("query", "")
    entity_id = params.get("entity_id")
    document_type = params.get("document_type")
    status = params.get("status")

    org_id = user.get("org_id", "")
    filters = []
    if org_id:
        filters.append(("organization_id", "==", org_id))
    if entity_id:
        filters.append(("entity_id", "==", entity_id))
    if document_type:
        filters.append(("document_type", "==", document_type))
    if status:
        filters.append(("status", "==", status))

    try:
        docs = get_documents("documents", filters=filters if filters else None, limit=50)
    except Exception:
        docs = []

    # Text filter on name, summary, type
    if query_text:
        q_lower = query_text.lower()
        docs = [
            d for d in docs
            if q_lower in (
                d.get("name", "") +
                d.get("ai_summary", "") +
                d.get("document_type", "") +
                d.get("entity_name", "")
            ).lower()
        ]

    if not docs:
        return {
            "message": f"No documents found matching '{query_text}'." if query_text else "No documents found with the given filters.",
            "data": {"type": "empty"},
        }

    table_rows = []
    for d in docs[:15]:
        table_rows.append({
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "type": d.get("document_type", ""),
            "entity": d.get("entity_name", ""),
            "entity_id": d.get("entity_id", ""),
            "score": d.get("score", 0),
            "status": d.get("compliance_status", d.get("status", "")),
            "expiry_date": d.get("expiry_date", d.get("expiration_date", "")),
        })

    return {
        "message": f"Found {len(docs)} document(s){' matching your search' if query_text else ''}.",
        "data": {
            "type": "document_table",
            "rows": table_rows,
            "total": len(docs),
        },
    }


async def tool_get_document_details(params: dict, user: dict) -> dict:
    """Get detailed information about a specific document."""
    document_id = params.get("document_id", "")
    document_name = params.get("document_name", "")

    doc = None
    if document_id:
        try:
            doc = get_document("documents", document_id)
        except Exception:
            pass

    # If no ID, try searching by name
    if not doc and document_name:
        try:
            all_docs = get_documents("documents", limit=100)
            name_lower = document_name.lower()
            for d in all_docs:
                if name_lower in d.get("name", "").lower():
                    doc = d
                    break
        except Exception:
            pass

    if not doc:
        return {
            "message": f"Could not find document{' with ID ' + document_id if document_id else ' named ' + document_name}.",
            "data": {"type": "empty"},
        }

    # Build detail card
    card = {
        "id": doc.get("id", ""),
        "name": doc.get("name", ""),
        "document_type": doc.get("document_type", ""),
        "entity_name": doc.get("entity_name", ""),
        "entity_id": doc.get("entity_id", ""),
        "status": doc.get("status", ""),
        "compliance_status": doc.get("compliance_status", ""),
        "score": doc.get("score", 0),
        "expiry_date": doc.get("expiry_date", doc.get("expiration_date", "")),
        "upload_date": doc.get("created_at", ""),
        "ai_summary": doc.get("ai_summary", ""),
        "parties": doc.get("parties", []),
        "key_clauses": doc.get("key_clauses", []),
        "risk_flags": doc.get("risk_flags", []),
        "dates": doc.get("dates", []),
    }

    summary_parts = [f"**{card['name']}** ({card['document_type']})"]
    if card["entity_name"]:
        summary_parts.append(f"Entity: {card['entity_name']}")
    if card["score"]:
        summary_parts.append(f"Compliance Score: {card['score']}")
    if card["status"]:
        summary_parts.append(f"Status: {card['status']}")
    if card["ai_summary"]:
        summary_parts.append(f"\n{card['ai_summary']}")
    if card["risk_flags"]:
        flags = card["risk_flags"]
        if isinstance(flags, list):
            summary_parts.append(f"\nRisk Flags: {', '.join(str(f) for f in flags[:5])}")

    return {
        "message": "\n".join(summary_parts),
        "data": {"type": "document_card", "document": card},
    }


async def tool_analyze_document(params: dict, user: dict) -> dict:
    """Run compliance gap analysis on a document."""
    document_id = params.get("document_id", "")

    doc = None
    if document_id:
        try:
            doc = get_document("documents", document_id)
        except Exception:
            pass

    if not doc:
        return {
            "message": f"Could not find document '{document_id}' to analyze.",
            "data": {"type": "empty"},
        }

    text = doc.get("extracted_text", doc.get("extracted_content", doc.get("ai_summary", "")))
    doc_type = doc.get("document_type", "unknown")

    # Run gap analysis
    gaps = analyze_compliance_gaps(
        doc_data={"text": text[:10000], "type": doc_type, "name": doc.get("name", "")},
        rules=[
            {"id": "R1", "name": "Document Validity", "requirement": "Must have valid expiry date"},
            {"id": "R2", "name": "Party Identification", "requirement": "All parties must be clearly identified"},
            {"id": "R3", "name": "Jurisdiction Specified", "requirement": "Governing law must be stated"},
            {"id": "R4", "name": "Insurance Coverage", "requirement": "Adequate insurance must be maintained"},
            {"id": "R5", "name": "Termination Clause", "requirement": "Clear termination provisions required"},
            {"id": "R6", "name": "Data Protection", "requirement": "Data handling obligations must be specified"},
        ],
    )

    # Build summary
    risk = gaps.get("risk_score", "MEDIUM")
    gap_count = len(gaps.get("compliance_gaps", []))
    rec_count = len(gaps.get("recommendations", []))
    summary = gaps.get("summary", "Analysis complete.")

    return {
        "message": f"**Analysis of {doc.get('name', 'Document')}**\n\nRisk Level: {risk}\nGaps Found: {gap_count}\nRecommendations: {rec_count}\n\n{summary}",
        "data": {
            "type": "gap_list",
            "document_id": document_id,
            "document_name": doc.get("name", ""),
            "risk_score": risk,
            "risk_score_value": gaps.get("risk_score_value", 50),
            "gaps": gaps.get("compliance_gaps", []),
            "recommendations": gaps.get("recommendations", []),
            "regulatory_requirements": gaps.get("regulatory_requirements", []),
        },
    }


async def tool_get_entity_info(params: dict, user: dict) -> dict:
    """Get entity/vendor compliance information."""
    entity_id = params.get("entity_id", "")
    entity_name = params.get("entity_name", "")

    entity = None
    if entity_id:
        try:
            entity = get_document("entities", entity_id)
        except Exception:
            pass

    # Try by name
    if not entity and entity_name:
        try:
            entities = get_documents("entities", limit=100)
            name_lower = entity_name.lower()
            for e in entities:
                if name_lower in e.get("name", "").lower():
                    entity = e
                    break
        except Exception:
            pass

    if not entity:
        return {
            "message": f"Could not find entity{' with ID ' + entity_id if entity_id else ' named ' + entity_name}.",
            "data": {"type": "empty"},
        }

    # Get documents for this entity
    try:
        docs = get_entity_documents(entity.get("id", ""))
    except Exception:
        docs = []

    # Get score breakdown
    try:
        score_data = calculate_entity_score(entity.get("id", ""))
    except Exception:
        score_data = {}

    card = {
        "id": entity.get("id", ""),
        "name": entity.get("name", ""),
        "entity_type": entity.get("entity_type", entity.get("type", "")),
        "compliance_score": entity.get("compliance_score", score_data.get("overall_score", 0)),
        "risk_level": entity.get("risk_level", score_data.get("risk_level", "")),
        "grade": score_data.get("grade", ""),
        "document_count": len(docs),
        "created_at": entity.get("created_at", ""),
        "contact_email": entity.get("contact_email", ""),
        "contact_name": entity.get("contact_name", ""),
    }

    doc_summary = []
    for d in docs[:10]:
        doc_summary.append({
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "type": d.get("document_type", ""),
            "status": d.get("status", ""),
            "score": d.get("score", 0),
        })

    msg_parts = [
        f"**{card['name']}**",
        f"Type: {card['entity_type']}" if card["entity_type"] else None,
        f"Compliance Score: {card['compliance_score']} (Grade: {card['grade']}, Risk: {card['risk_level']})" if card["compliance_score"] else None,
        f"Documents: {card['document_count']}",
    ]

    return {
        "message": "\n".join(p for p in msg_parts if p),
        "data": {
            "type": "entity_card",
            "entity": card,
            "documents": doc_summary,
            "score_breakdown": score_data.get("breakdown", {}),
        },
    }


async def tool_list_entities(params: dict, user: dict) -> dict:
    """List all entities/vendors with scores."""
    entity_type = params.get("entity_type")
    risk_level = params.get("risk_level")
    org_id = user.get("org_id", "")

    filters = []
    if org_id:
        filters.append(("organization_id", "==", org_id))
    if entity_type:
        filters.append(("entity_type", "==", entity_type))

    try:
        entities = get_documents("entities", filters=filters if filters else None, limit=100)
    except Exception:
        entities = []

    # Filter by risk level in-memory if needed
    if risk_level and entities:
        entities = [e for e in entities if e.get("risk_level", "").lower() == risk_level.lower()]

    if not entities:
        return {
            "message": "No entities found.",
            "data": {"type": "empty"},
        }

    rows = []
    for e in entities:
        rows.append({
            "id": e.get("id", ""),
            "name": e.get("name", ""),
            "type": e.get("entity_type", e.get("type", "")),
            "compliance_score": e.get("compliance_score", 0),
            "risk_level": e.get("risk_level", ""),
            "document_count": e.get("document_count", 0),
        })

    # Sort by score descending
    rows.sort(key=lambda x: x.get("compliance_score", 0), reverse=True)

    return {
        "message": f"Found {len(entities)} entity/entities.",
        "data": {
            "type": "entity_table",
            "rows": rows,
            "total": len(entities),
        },
    }


async def tool_get_compliance_score(params: dict, user: dict) -> dict:
    """Get compliance score for an entity or portfolio-wide."""
    entity_id = params.get("entity_id")

    if entity_id:
        try:
            score_data = get_score_breakdown(entity_id)
        except Exception:
            score_data = {}

        if not score_data:
            return {
                "message": f"Could not calculate score for entity '{entity_id}'.",
                "data": {"type": "empty"},
            }

        msg_parts = [
            f"**Compliance Score: {score_data.get('overall_score', 0)}** (Grade: {score_data.get('grade', 'N/A')})",
            f"Risk Level: {score_data.get('risk_level', 'unknown')}",
            "",
            "**Category Breakdown:**",
        ]
        breakdown = score_data.get("breakdown", {})
        for cat, info in breakdown.items():
            if isinstance(info, dict):
                msg_parts.append(f"  - {cat.replace('_', ' ').title()}: {info.get('score', 0)} (weight: {info.get('weight', 0)}%)")

        recs = score_data.get("recommendations", [])
        if recs:
            msg_parts.append("\n**Recommendations:**")
            for r in recs[:5]:
                msg_parts.append(f"  [{r.get('priority', 'medium').upper()}] {r.get('message', '')}")

        return {
            "message": "\n".join(msg_parts),
            "data": {
                "type": "score_chart",
                "entity_id": entity_id,
                "overall_score": score_data.get("overall_score", 0),
                "grade": score_data.get("grade", ""),
                "risk_level": score_data.get("risk_level", ""),
                "breakdown": breakdown,
                "recommendations": recs,
                "document_scores": score_data.get("document_scores", []),
            },
        }
    else:
        # Portfolio-wide score
        org_id = user.get("org_id", "")
        filters = [("organization_id", "==", org_id)] if org_id else None
        try:
            entities = get_documents("entities", filters=filters, limit=100)
        except Exception:
            entities = []

        if not entities:
            return {
                "message": "No entities found to calculate portfolio score.",
                "data": {"type": "empty"},
            }

        scores = []
        entity_rows = []
        for e in entities:
            s = e.get("compliance_score", 0)
            if isinstance(s, (int, float)) and s > 0:
                scores.append(s)
            entity_rows.append({
                "name": e.get("name", ""),
                "score": s,
                "risk_level": e.get("risk_level", ""),
            })

        avg = round(sum(scores) / len(scores), 1) if scores else 0

        return {
            "message": f"**Portfolio Compliance Score: {avg}**\nAcross {len(entities)} entities.",
            "data": {
                "type": "score_chart",
                "portfolio_score": avg,
                "entity_count": len(entities),
                "entities": entity_rows,
            },
        }


async def tool_get_analytics(params: dict, user: dict) -> dict:
    """Get compliance analytics, trends, risk matrix."""
    metric_type = params.get("metric_type", "summary")
    org_id = user.get("org_id", "")
    filters = [("organization_id", "==", org_id)] if org_id else None

    if metric_type == "summary":
        try:
            docs = get_documents("documents", filters=filters, limit=500)
            entities = get_documents("entities", filters=filters, limit=100)
        except Exception:
            docs, entities = [], []

        now = datetime.now(timezone.utc)
        expired = 0
        exp_30 = 0
        status_dist = {}
        type_dist = {}

        for d in docs:
            st = d.get("status", "unknown")
            status_dist[st] = status_dist.get(st, 0) + 1
            dt = d.get("document_type", "Other")
            type_dist[dt] = type_dist.get(dt, 0) + 1
            exp_str = d.get("expiry_date") or d.get("expiration_date")
            if exp_str:
                try:
                    if isinstance(exp_str, str):
                        exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    else:
                        exp = exp_str
                    if exp < now:
                        expired += 1
                    elif exp < now + timedelta(days=30):
                        exp_30 += 1
                except (ValueError, TypeError):
                    pass

        entity_scores = [e.get("compliance_score", 0) for e in entities if isinstance(e.get("compliance_score"), (int, float)) and e.get("compliance_score", 0) > 0]
        avg_score = round(sum(entity_scores) / len(entity_scores), 1) if entity_scores else 0

        msg = (
            f"**Compliance Dashboard Summary**\n"
            f"Total Documents: {len(docs)}\n"
            f"Total Entities: {len(entities)}\n"
            f"Average Score: {avg_score}\n"
            f"Expired: {expired} | Expiring in 30 days: {exp_30}"
        )

        return {
            "message": msg,
            "data": {
                "type": "analytics_summary",
                "total_documents": len(docs),
                "total_entities": len(entities),
                "avg_compliance_score": avg_score,
                "expired": expired,
                "expiring_30d": exp_30,
                "status_distribution": status_dist,
                "document_type_distribution": type_dist,
            },
        }

    elif metric_type == "risk_matrix":
        try:
            entities = get_documents("entities", filters=filters, limit=100)
        except Exception:
            entities = []

        matrix = []
        for e in entities:
            try:
                score = calculate_entity_score(e.get("id", ""))
            except Exception:
                score = {}
            matrix.append({
                "entity_id": e.get("id", ""),
                "entity_name": e.get("name", ""),
                "score": score.get("overall_score", e.get("compliance_score", 0)),
                "risk_level": score.get("risk_level", e.get("risk_level", "")),
                "document_count": score.get("document_count", 0),
            })

        matrix.sort(key=lambda x: x.get("score", 0))

        msg_parts = ["**Risk Matrix**"]
        for item in matrix:
            risk_emoji = {"low": "LOW", "medium": "MED", "high": "HIGH", "critical": "CRIT"}.get(item["risk_level"], "???")
            msg_parts.append(f"  {item['entity_name']}: {item['score']} [{risk_emoji}]")

        return {
            "message": "\n".join(msg_parts),
            "data": {"type": "risk_matrix", "matrix": matrix, "count": len(matrix)},
        }

    elif metric_type == "expiry_forecast":
        try:
            docs = get_documents("documents", filters=filters, limit=500)
        except Exception:
            docs = []

        now = datetime.now(timezone.utc)
        buckets = {"overdue": [], "next_30_days": [], "next_60_days": [], "next_90_days": []}

        for d in docs:
            exp_str = d.get("expiry_date") or d.get("expiration_date")
            if not exp_str:
                continue
            try:
                if isinstance(exp_str, str):
                    if len(exp_str) == 10:
                        exp = datetime.fromisoformat(exp_str + "T00:00:00+00:00")
                    else:
                        exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                else:
                    exp = exp_str
                delta = (exp - now).days
                entry = {
                    "doc_id": d.get("id", ""),
                    "name": d.get("name", ""),
                    "entity_name": d.get("entity_name", ""),
                    "expiry_date": exp.isoformat(),
                    "document_type": d.get("document_type", ""),
                }
                if delta < 0:
                    entry["days_overdue"] = abs(delta)
                    buckets["overdue"].append(entry)
                elif delta <= 30:
                    entry["days_until_expiry"] = delta
                    buckets["next_30_days"].append(entry)
                elif delta <= 60:
                    entry["days_until_expiry"] = delta
                    buckets["next_60_days"].append(entry)
                elif delta <= 90:
                    entry["days_until_expiry"] = delta
                    buckets["next_90_days"].append(entry)
            except (ValueError, TypeError):
                pass

        total = sum(len(v) for v in buckets.values())
        msg = (
            f"**Expiry Forecast**\n"
            f"Overdue: {len(buckets['overdue'])}\n"
            f"Next 30 days: {len(buckets['next_30_days'])}\n"
            f"Next 60 days: {len(buckets['next_60_days'])}\n"
            f"Next 90 days: {len(buckets['next_90_days'])}"
        )

        return {
            "message": msg,
            "data": {
                "type": "expiry_forecast",
                "buckets": buckets,
                "summary": {
                    "overdue_count": len(buckets["overdue"]),
                    "next_30_count": len(buckets["next_30_days"]),
                    "next_60_count": len(buckets["next_60_days"]),
                    "next_90_count": len(buckets["next_90_days"]),
                },
            },
        }

    elif metric_type == "trends":
        try:
            history = get_documents(
                "analytics_snapshots",
                order_by="date",
                direction="DESCENDING",
                limit=12,
            )
        except Exception:
            history = []

        if history:
            return {
                "message": f"Showing compliance trends for the last {len(history)} months.",
                "data": {"type": "trends", "trends": history},
            }

        # Demo trends
        now = datetime.now(timezone.utc)
        trends = []
        base = 62.0
        for i in range(12, 0, -1):
            d = now - timedelta(days=30 * i)
            score = min(95, base + (12 - i) * 2.8 + (hash(str(i + 42)) % 8 - 3))
            trends.append({
                "date": d.strftime("%Y-%m"),
                "avg_score": round(score, 1),
                "total_docs": 30 + i * 2,
            })

        return {
            "message": "Showing compliance trends for the last 12 months.",
            "data": {"type": "trends", "trends": trends},
        }

    return {
        "message": f"Unknown metric type '{metric_type}'. Available: summary, risk_matrix, expiry_forecast, trends.",
        "data": {"type": "text"},
    }


async def tool_semantic_search(params: dict, user: dict) -> dict:
    """Semantic search across documents using RAG (Pinecone)."""
    query_text = params.get("query", "")
    top_k = min(params.get("top_k", 5), 10)
    org_id = user.get("org_id", "")

    if not query_text:
        return {"message": "Please provide a search query.", "data": {"type": "empty"}}

    # Generate embedding
    try:
        embedding = generate_embeddings(query_text)
    except Exception:
        embedding = [0.0] * 768

    filter_meta = {}
    if org_id:
        filter_meta["organization_id"] = org_id

    # Query Pinecone
    try:
        matches = query_similar(
            vector=embedding,
            top_k=top_k,
            filter_metadata=filter_meta if filter_meta else None,
        )
    except Exception:
        matches = []

    # If no Pinecone results, fallback to Firestore text search
    if not matches:
        try:
            all_docs = get_documents("documents", limit=50)
            q_lower = query_text.lower()
            relevant = []
            for d in all_docs:
                searchable = (
                    d.get("name", "") +
                    d.get("ai_summary", "") +
                    d.get("extracted_content", "") +
                    d.get("document_type", "")
                ).lower()
                if q_lower in searchable:
                    relevant.append(d)
            if relevant:
                sources = []
                for d in relevant[:top_k]:
                    sources.append({
                        "name": d.get("name", "Document"),
                        "document_id": d.get("id", ""),
                        "text": (d.get("ai_summary", "") or d.get("extracted_content", ""))[:500],
                        "relevance": 0.7,
                    })

                # Use Gemini to answer the query with context
                context_docs = [{"name": s["name"], "text": s["text"]} for s in sources]
                answer = chat_completion(
                    [{"role": "user", "content": query_text}],
                    context_docs,
                )

                return {
                    "message": answer,
                    "data": {"type": "search_results", "results": sources, "total": len(sources)},
                    "sources": [{"name": s["name"], "relevance": s["relevance"]} for s in sources],
                }
        except Exception:
            pass

        return {
            "message": f"No relevant documents found for '{query_text}'. Try uploading more documents or refining your query.",
            "data": {"type": "empty"},
        }

    # Format Pinecone results
    sources = []
    for m in matches:
        sources.append({
            "name": m.get("metadata", {}).get("name", "Document"),
            "document_id": m.get("id", ""),
            "text": m.get("metadata", {}).get("text", "")[:500],
            "relevance": round(m.get("score", 0), 3),
        })

    # Use Gemini to answer with context
    context_docs = [{"name": s["name"], "text": s["text"]} for s in sources]
    answer = chat_completion(
        [{"role": "user", "content": query_text}],
        context_docs,
    )

    return {
        "message": answer,
        "data": {"type": "search_results", "results": sources, "total": len(sources)},
        "sources": [{"name": s["name"], "relevance": s["relevance"]} for s in sources],
    }


async def tool_get_expiring_docs(params: dict, user: dict) -> dict:
    """Get documents expiring within N days."""
    days = params.get("days", 30)
    org_id = user.get("org_id", "")

    filters = []
    if org_id:
        filters.append(("organization_id", "==", org_id))

    try:
        docs = get_documents("documents", filters=filters if filters else None, limit=500)
    except Exception:
        docs = []

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    expiring = []
    overdue = []

    for d in docs:
        exp_str = d.get("expiry_date") or d.get("expiration_date")
        if not exp_str:
            continue
        try:
            if isinstance(exp_str, str):
                if len(exp_str) == 10:
                    exp = datetime.fromisoformat(exp_str + "T00:00:00+00:00")
                else:
                    exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            else:
                exp = exp_str
            delta = (exp - now).days
            entry = {
                "id": d.get("id", ""),
                "name": d.get("name", ""),
                "entity_name": d.get("entity_name", ""),
                "document_type": d.get("document_type", ""),
                "expiry_date": exp.isoformat(),
            }
            if delta < 0:
                entry["days_overdue"] = abs(delta)
                overdue.append(entry)
            elif exp <= cutoff:
                entry["days_until_expiry"] = delta
                expiring.append(entry)
        except (ValueError, TypeError):
            pass

    expiring.sort(key=lambda x: x.get("days_until_expiry", 999))
    overdue.sort(key=lambda x: x.get("days_overdue", 0), reverse=True)

    total = len(expiring) + len(overdue)
    if total == 0:
        return {
            "message": f"No documents expiring within the next {days} days. All clear!",
            "data": {"type": "empty"},
        }

    msg_parts = []
    if overdue:
        msg_parts.append(f"**{len(overdue)} OVERDUE document(s):**")
        for d in overdue[:5]:
            msg_parts.append(f"  - {d['name']} ({d['entity_name']}) - {d['days_overdue']} days overdue")
    if expiring:
        msg_parts.append(f"\n**{len(expiring)} document(s) expiring within {days} days:**")
        for d in expiring[:5]:
            msg_parts.append(f"  - {d['name']} ({d['entity_name']}) - {d['days_until_expiry']} days left")

    return {
        "message": "\n".join(msg_parts),
        "data": {
            "type": "expiry_list",
            "overdue": overdue[:20],
            "expiring": expiring[:20],
            "total_overdue": len(overdue),
            "total_expiring": len(expiring),
        },
    }


async def tool_get_gaps(params: dict, user: dict) -> dict:
    """Get compliance gaps for an entity."""
    entity_id = params.get("entity_id", "")

    if not entity_id:
        return {"message": "Please specify an entity to check for compliance gaps.", "data": {"type": "empty"}}

    try:
        entity = get_document("entities", entity_id)
    except Exception:
        entity = None

    if not entity:
        return {"message": f"Entity '{entity_id}' not found.", "data": {"type": "empty"}}

    try:
        docs = get_entity_documents(entity_id)
    except Exception:
        docs = []

    # Calculate score breakdown which includes gaps
    try:
        breakdown = get_score_breakdown(entity_id)
    except Exception:
        breakdown = {}

    # Also run AI gap analysis on documents if available
    all_gaps = []
    missing_types = breakdown.get("breakdown", {}).get("completeness", {}).get("missing_types", [])
    recs = breakdown.get("recommendations", [])

    if missing_types:
        for mt in missing_types:
            all_gaps.append({
                "title": f"Missing {mt}",
                "description": f"No {mt} document found for this entity.",
                "severity": "high",
            })

    expired_count = breakdown.get("breakdown", {}).get("expiry", {}).get("expired_docs", 0)
    if expired_count > 0:
        all_gaps.append({
            "title": "Expired Documents",
            "description": f"{expired_count} document(s) have expired and need renewal.",
            "severity": "critical",
        })

    expiring = breakdown.get("breakdown", {}).get("expiry", {}).get("expiring_soon", 0)
    if expiring > 0:
        all_gaps.append({
            "title": "Documents Expiring Soon",
            "description": f"{expiring} document(s) expiring within 30 days.",
            "severity": "high",
        })

    compliance_score = breakdown.get("breakdown", {}).get("compliance", {}).get("score", 100)
    if compliance_score < 70:
        all_gaps.append({
            "title": "Low Approval Rate",
            "description": f"Only {compliance_score}% of documents are approved.",
            "severity": "medium",
        })

    msg_parts = [f"**Compliance Gaps for {entity.get('name', entity_id)}**"]
    if not all_gaps:
        msg_parts.append("No significant compliance gaps detected.")
    else:
        for g in all_gaps:
            sev = g.get("severity", "medium").upper()
            msg_parts.append(f"  [{sev}] {g['title']}: {g['description']}")

    if recs:
        msg_parts.append("\n**Recommendations:**")
        for r in recs[:5]:
            msg_parts.append(f"  - [{r.get('priority', 'medium').upper()}] {r.get('message', '')}")

    return {
        "message": "\n".join(msg_parts),
        "data": {
            "type": "gap_list",
            "entity_id": entity_id,
            "entity_name": entity.get("name", ""),
            "gaps": all_gaps,
            "recommendations": recs,
            "overall_score": breakdown.get("overall_score", 0),
            "grade": breakdown.get("grade", ""),
        },
    }


async def tool_compare_entities(params: dict, user: dict) -> dict:
    """Compare compliance across multiple entities."""
    entity_ids = params.get("entity_ids", [])
    org_id = user.get("org_id", "")

    # If no specific IDs, compare all entities
    if not entity_ids:
        filters = [("organization_id", "==", org_id)] if org_id else None
        try:
            entities = get_documents("entities", filters=filters, limit=20)
            entity_ids = [e.get("id", "") for e in entities if e.get("id")]
        except Exception:
            entities = []

    if not entity_ids:
        return {"message": "No entities available to compare.", "data": {"type": "empty"}}

    comparison = []
    for eid in entity_ids[:10]:
        try:
            entity = get_document("entities", eid)
            score_data = calculate_entity_score(eid)
        except Exception:
            entity = None
            score_data = {}

        if entity:
            comparison.append({
                "entity_id": eid,
                "name": entity.get("name", ""),
                "overall_score": score_data.get("overall_score", entity.get("compliance_score", 0)),
                "grade": score_data.get("grade", ""),
                "risk_level": score_data.get("risk_level", entity.get("risk_level", "")),
                "document_count": score_data.get("document_count", 0),
                "breakdown": score_data.get("breakdown", {}),
            })

    if not comparison:
        return {"message": "Could not retrieve entity data for comparison.", "data": {"type": "empty"}}

    comparison.sort(key=lambda x: x.get("overall_score", 0), reverse=True)

    msg_parts = ["**Entity Compliance Comparison**\n"]
    for i, c in enumerate(comparison, 1):
        msg_parts.append(
            f"{i}. **{c['name']}** - Score: {c['overall_score']} "
            f"(Grade: {c['grade']}, Risk: {c['risk_level']}, Docs: {c['document_count']})"
        )

    best = comparison[0]["name"] if comparison else "N/A"
    worst = comparison[-1]["name"] if comparison else "N/A"
    msg_parts.append(f"\nBest performing: {best}")
    msg_parts.append(f"Needs attention: {worst}")

    return {
        "message": "\n".join(msg_parts),
        "data": {
            "type": "comparison_table",
            "entities": comparison,
            "best": comparison[0] if comparison else None,
            "worst": comparison[-1] if comparison else None,
        },
    }


async def tool_create_entity(params: dict, user: dict) -> dict:
    """Create a new entity/vendor."""
    name = params.get("name", "")
    entity_type = params.get("entity_type", "property")

    if not name:
        return {"message": "Please provide a name for the new entity.", "data": {"type": "empty"}}

    org_id = user.get("org_id", "")

    entity_data = {
        "name": name,
        "entity_type": entity_type,
        "organization_id": org_id,
        "compliance_score": 0,
        "risk_level": "unknown",
        "document_count": 0,
        "status": "active",
    }

    # Optional fields
    for field in ["contact_name", "contact_email", "address", "notes"]:
        if params.get(field):
            entity_data[field] = params[field]

    try:
        entity_id = create_document("entities", entity_data)
        return {
            "message": f"Entity **{name}** created successfully (ID: {entity_id}).",
            "data": {
                "type": "entity_card",
                "entity": {**entity_data, "id": entity_id},
            },
        }
    except Exception as e:
        return {
            "message": f"Failed to create entity: {str(e)}",
            "data": {"type": "error"},
        }


async def tool_set_reminder(params: dict, user: dict) -> dict:
    """Create a reminder for a document or entity."""
    from backend.services.firestore_service import create_document as fs_create

    title = params.get("title", "Compliance Reminder")
    description = params.get("description", "")
    due_date = params.get("due_date", "")
    entity_id = params.get("entity_id", "")
    document_id = params.get("document_id", "")
    reminder_type = params.get("reminder_type", "general")
    recipient_email = params.get("recipient_email", "")

    org_id = user.get("org_id", "")

    reminder_data = {
        "title": title,
        "description": description,
        "due_date": due_date,
        "entity_id": entity_id,
        "document_id": document_id,
        "reminder_type": reminder_type,
        "recipient_email": recipient_email,
        "organization_id": org_id,
        "status": "pending",
        "created_by": user.get("email", ""),
    }

    try:
        reminder_id = fs_create("reminders", reminder_data)
        return {
            "message": f"Reminder set: **{title}**" + (f"\nDue: {due_date}" if due_date else "") + (f"\nFor: {recipient_email}" if recipient_email else ""),
            "data": {
                "type": "reminder_card",
                "reminder": {**reminder_data, "id": reminder_id},
            },
        }
    except Exception as e:
        return {
            "message": f"Failed to create reminder: {str(e)}",
            "data": {"type": "error"},
        }


async def tool_general_answer(params: dict, user: dict) -> dict:
    """Answer general compliance questions using AI with RAG context.

    Routes through n8n Copilot Agent workflow (Gemini + Pinecone + Firebase)
    when available, falls back to local Gemini + Pinecone.
    """
    question = params.get("question", "")
    context_doc_ids = params.get("context_docs", [])
    conversation_history = params.get("conversation_history", [])

    if not question:
        return {"message": "Please ask a question.", "data": {"type": "text"}}

    # --- Try n8n Copilot Agent first (has Gemini + Pinecone + Firebase built in) ---
    try:
        # Build context string from recent docs if available
        context_str = ""
        if context_doc_ids:
            doc_names = []
            for doc_id in context_doc_ids[:3]:
                try:
                    doc = get_document("documents", doc_id)
                    if doc:
                        doc_names.append(doc.get("name", ""))
                except Exception:
                    pass
            if doc_names:
                context_str = f"Referenced documents: {', '.join(doc_names)}"

        n8n_result = await trigger_copilot_agent(
            query=question,
            context=context_str,
            conversation_history=conversation_history[-5:] if conversation_history else [],
        )

        # If n8n returned a real response, use it
        if n8n_result.get("status") == "ok" and n8n_result.get("response"):
            sources = n8n_result.get("sources", [])
            if not sources:
                # Try to extract doc names from the response text
                sources = _extract_sources_from_response(n8n_result["response"])
            return {
                "message": n8n_result["response"],
                "data": {"type": "text"},
                "sources": sources,
            }
    except Exception as e:
        logger.warning("n8n copilot agent failed, falling back to local: %s", e)

    # --- Fallback: Local Gemini + Pinecone ---
    context_docs = []

    if context_doc_ids:
        for doc_id in context_doc_ids[:5]:
            try:
                doc = get_document("documents", doc_id)
                if doc:
                    context_docs.append({
                        "name": doc.get("name", "Document"),
                        "text": (doc.get("extracted_content", "") or doc.get("ai_summary", ""))[:3000],
                    })
            except Exception:
                pass

    # Try RAG if no explicit context
    if not context_docs:
        try:
            embedding = generate_embeddings(question)
            org_id = user.get("org_id", "")
            filter_meta = {"organization_id": org_id} if org_id else None
            matches = query_similar(vector=embedding, top_k=3, filter_metadata=filter_meta)
            for m in matches:
                context_docs.append({
                    "name": m.get("metadata", {}).get("name", "Document"),
                    "text": m.get("metadata", {}).get("text", "")[:3000],
                })
        except Exception:
            pass

    # If still no context, try fetching recent docs from Firestore
    if not context_docs:
        try:
            recent_docs = get_documents("documents", limit=5)
            for d in recent_docs:
                text = d.get("ai_summary", "") or d.get("extracted_content", "")
                if text:
                    context_docs.append({"name": d.get("name", "Document"), "text": text[:2000]})
        except Exception:
            pass

    answer = chat_completion(
        [{"role": "user", "content": question}],
        context_docs if context_docs else None,
    )

    sources = [{"name": c["name"], "relevance": 0.8} for c in context_docs[:5]]

    return {
        "message": answer,
        "data": {"type": "text"},
        "sources": sources,
    }


def _extract_sources_from_response(text: str) -> list:
    """Try to extract document names mentioned in the AI response."""
    import re
    # Look for common patterns like "MSA1.pdf", "document_name.pdf", etc.
    pdf_refs = re.findall(r'\b[\w\-]+\.pdf\b', text, re.IGNORECASE)
    # Also look for quoted document names
    quoted = re.findall(r'"([^"]+)"', text)
    sources = []
    seen = set()
    for name in pdf_refs + quoted:
        if name.lower() not in seen and len(name) < 100:
            sources.append({"name": name, "relevance": 0.8})
            seen.add(name.lower())
    return sources[:5]


async def tool_upload_document(params: dict, user: dict) -> dict:
    """Prompt user to upload a document via the chat interface."""
    entity_name = params.get("entity_name", "")
    document_type = params.get("document_type", "")

    msg = "Please select a file to upload."
    if entity_name:
        msg = f"Please select a file to upload for **{entity_name}**."

    return {
        "message": msg,
        "data": {
            "type": "upload_prompt",
            "action": "upload",
            "entity_name": entity_name,
            "document_type": document_type,
        },
    }


async def tool_replace_document(params: dict, user: dict) -> dict:
    """Prompt user to replace an existing document."""
    document_id = params.get("document_id", "")
    document_name = params.get("document_name", "")

    doc = None
    if document_id:
        try:
            doc = get_document("documents", document_id)
        except Exception:
            pass

    if not doc and document_name:
        try:
            all_docs = get_documents("documents", limit=100)
            name_lower = document_name.lower()
            for d in all_docs:
                if name_lower in d.get("name", "").lower():
                    doc = d
                    break
        except Exception:
            pass

    if not doc:
        return {
            "message": f"Could not find document to replace{': ' + document_name if document_name else ''}. Please specify the document name.",
            "data": {"type": "empty"},
        }

    return {
        "message": f"Please select a replacement file for **{doc.get('name', 'document')}**.",
        "data": {
            "type": "upload_prompt",
            "action": "replace",
            "document_id": doc.get("id", ""),
            "document_name": doc.get("name", ""),
            "entity_id": doc.get("entity_id", ""),
            "entity_name": doc.get("entity_name", ""),
            "document_type": doc.get("document_type", ""),
        },
    }


async def tool_run_full_gap_analysis(params: dict, user: dict) -> dict:
    """Run comprehensive compliance risk analysis via n8n workflow."""
    entity_id = params.get("entity_id", "")
    entity_name = params.get("entity_name", "")

    # Resolve entity (reuse pattern from tool_get_entity_info)
    entity = None
    if entity_id:
        try:
            entity = get_document("entities", entity_id)
        except Exception:
            pass

    if not entity and entity_name:
        try:
            entities = get_documents("entities", limit=100)
            name_lower = entity_name.lower()
            for e in entities:
                if name_lower in e.get("name", "").lower():
                    entity = e
                    entity_id = e.get("id", "")
                    break
        except Exception:
            pass

    if not entity:
        return {
            "message": "Entity not found. Please specify a valid entity name or ID.",
            "data": {"type": "empty"},
        }

    entity_id = entity.get("id", entity_id)

    # Get documents for this entity
    try:
        docs = get_entity_documents(entity_id)
    except Exception:
        docs = []

    doc_ids = [d.get("id") for d in docs if d.get("id")]
    org_id = user.get("org_id", "")

    # Try n8n Risk Analysis Agent
    try:
        n8n_result = await trigger_risk_analysis(entity_id, doc_ids, org_id)

        if n8n_result and n8n_result.get("status") != "demo":
            gaps = n8n_result.get("gaps", n8n_result.get("compliance_gaps", []))
            risk_score = n8n_result.get("risk_score", n8n_result.get("risk_level", "MEDIUM"))
            recommendations = n8n_result.get("recommendations", [])
            summary = n8n_result.get("summary", "Risk analysis complete.")

            return {
                "message": f"**Full Risk Analysis for {entity.get('name')}**\n\nRisk Level: {risk_score}\nGaps Found: {len(gaps)}\nDocuments Analyzed: {len(docs)}\n\n{summary}",
                "data": {
                    "type": "risk_analysis",
                    "entity_id": entity_id,
                    "entity_name": entity.get("name", ""),
                    "risk_score": str(risk_score).upper(),
                    "gaps": gaps,
                    "recommendations": recommendations,
                    "document_count": len(docs),
                },
            }
    except Exception as e:
        logger.warning(f"n8n risk analysis failed, falling back to local: {e}")

    # Fallback: use local gap analysis on each document
    all_gaps = []
    all_recs = []
    for d in docs[:5]:  # Limit to 5 docs for performance
        text = d.get("extracted_text", d.get("extracted_content", d.get("ai_summary", "")))
        if not text:
            continue
        try:
            result = analyze_compliance_gaps(
                doc_data={"text": text[:10000], "type": d.get("document_type", ""), "name": d.get("name", "")},
                rules=[
                    {"id": "R1", "name": "Document Validity", "requirement": "Must have valid expiry date"},
                    {"id": "R2", "name": "Party Identification", "requirement": "All parties must be clearly identified"},
                    {"id": "R3", "name": "Jurisdiction Specified", "requirement": "Governing law must be stated"},
                    {"id": "R4", "name": "Insurance Coverage", "requirement": "Adequate insurance must be maintained"},
                    {"id": "R5", "name": "Termination Clause", "requirement": "Clear termination provisions required"},
                    {"id": "R6", "name": "Data Protection", "requirement": "Data handling obligations must be specified"},
                ],
            )
            all_gaps.extend(result.get("compliance_gaps", []))
            all_recs.extend(result.get("recommendations", []))
        except Exception:
            pass

    # Deduplicate
    seen = set()
    unique_gaps = []
    for g in all_gaps:
        key = g.get("description", g.get("gap", ""))[:50]
        if key not in seen:
            seen.add(key)
            unique_gaps.append(g)

    risk_level = "LOW"
    critical_count = sum(1 for g in unique_gaps if g.get("severity", "").lower() == "critical")
    high_count = sum(1 for g in unique_gaps if g.get("severity", "").lower() == "high")
    if critical_count > 0:
        risk_level = "CRITICAL"
    elif high_count > 2:
        risk_level = "HIGH"
    elif len(unique_gaps) > 3:
        risk_level = "MEDIUM"

    return {
        "message": f"**Risk Analysis for {entity.get('name')}**\n\nRisk Level: {risk_level}\nGaps Found: {len(unique_gaps)}\nDocuments Analyzed: {len(docs)}\n\nAnalysis complete with {len(all_recs)} recommendations.",
        "data": {
            "type": "risk_analysis",
            "entity_id": entity_id,
            "entity_name": entity.get("name", ""),
            "risk_score": risk_level,
            "gaps": unique_gaps,
            "recommendations": all_recs[:10],
            "document_count": len(docs),
        },
    }


# ===================================================================
# AGENT TOOLS REGISTRY
# ===================================================================

AGENT_TOOLS = {
    "search_documents": {
        "description": "Search for documents by name, type, entity, or content",
        "function": tool_search_documents,
        "parameters": ["query", "entity_id", "document_type", "status"],
    },
    "get_document_details": {
        "description": "Get detailed information about a specific document",
        "function": tool_get_document_details,
        "parameters": ["document_id", "document_name"],
    },
    "analyze_document": {
        "description": "Run compliance gap analysis on a document",
        "function": tool_analyze_document,
        "parameters": ["document_id"],
    },
    "get_entity_info": {
        "description": "Get entity/vendor compliance information and documents",
        "function": tool_get_entity_info,
        "parameters": ["entity_id", "entity_name"],
    },
    "list_entities": {
        "description": "List all entities/vendors with compliance scores",
        "function": tool_list_entities,
        "parameters": ["entity_type", "risk_level"],
    },
    "get_compliance_score": {
        "description": "Get compliance score breakdown for an entity or portfolio",
        "function": tool_get_compliance_score,
        "parameters": ["entity_id"],
    },
    "get_analytics": {
        "description": "Get compliance analytics: summary, trends, risk_matrix, or expiry_forecast",
        "function": tool_get_analytics,
        "parameters": ["metric_type"],
    },
    "search_by_content": {
        "description": "Semantic search across all documents using AI (RAG). Use for questions about document content, clauses, terms, etc.",
        "function": tool_semantic_search,
        "parameters": ["query", "top_k"],
    },
    "get_expiring_documents": {
        "description": "Get documents expiring soon within N days",
        "function": tool_get_expiring_docs,
        "parameters": ["days"],
    },
    "get_compliance_gaps": {
        "description": "Get compliance gaps and missing items for an entity",
        "function": tool_get_gaps,
        "parameters": ["entity_id"],
    },
    "compare_entities": {
        "description": "Compare compliance scores across entities side by side",
        "function": tool_compare_entities,
        "parameters": ["entity_ids"],
    },
    "create_entity": {
        "description": "Create a new entity/vendor/property",
        "function": tool_create_entity,
        "parameters": ["name", "entity_type", "contact_name", "contact_email"],
    },
    "set_reminder": {
        "description": "Create a reminder for document renewal, compliance review, etc.",
        "function": tool_set_reminder,
        "parameters": ["title", "description", "due_date", "entity_id", "document_id", "recipient_email", "reminder_type"],
    },
    "general_question": {
        "description": "Answer general compliance questions using AI with document context",
        "function": tool_general_answer,
        "parameters": ["question", "context_docs"],
    },
    "upload_document": {
        "description": "Upload a new document via the chat interface",
        "function": tool_upload_document,
        "parameters": ["entity_name", "document_type"],
    },
    "replace_document": {
        "description": "Replace an existing document with a new version",
        "function": tool_replace_document,
        "parameters": ["document_id", "document_name"],
    },
    "run_full_gap_analysis": {
        "description": "Run comprehensive compliance risk analysis for an entity",
        "function": tool_run_full_gap_analysis,
        "parameters": ["entity_id", "entity_name"],
    },
}


# ===================================================================
# INTENT CLASSIFICATION
# ===================================================================

def _build_classification_prompt(message: str, conversation_history: list, context: dict) -> str:
    """Build the prompt for Gemini to classify user intent."""
    tools_desc = "\n".join(
        f"- {name}: {tool['description']} (params: {', '.join(tool['parameters'])})"
        for name, tool in AGENT_TOOLS.items()
    )

    history_text = ""
    if conversation_history:
        recent = conversation_history[-6:]
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            history_text += f"{role}: {content}\n"

    context_text = ""
    if context:
        if context.get("entity_id"):
            context_text += f"Current entity context: {context['entity_id']}\n"
        if context.get("document_id"):
            context_text += f"Current document context: {context['document_id']}\n"

    return f"""You are a compliance copilot agent. Classify the user's intent and extract parameters.
You MUST return valid JSON only, no other text.

Available tools:
{tools_desc}

{f"Recent conversation:{chr(10)}{history_text}" if history_text else ""}
{f"Context:{chr(10)}{context_text}" if context_text else ""}

User message: {message}

Rules for classification:
1. If the user asks about a specific document (by name or ID), use "get_document_details" or "analyze_document".
2. If the user asks to find/search/list documents, use "search_documents".
3. If the user asks about an entity/vendor/property (info, details), use "get_entity_info".
4. If the user asks to list/show all entities, use "list_entities".
5. If the user asks about scores or score breakdown, use "get_compliance_score".
6. If the user asks about analytics, dashboard, summary, overview, use "get_analytics" with appropriate metric_type.
7. If the user asks questions about document content, clauses, terms, or needs AI answers from docs, use "search_by_content".
8. If the user asks about expiring/expired documents or renewals, use "get_expiring_documents".
9. If the user asks about compliance gaps or missing items, use "get_compliance_gaps".
10. If the user asks to compare entities or benchmark, use "compare_entities".
11. If the user wants to create a new entity, use "create_entity".
12. If the user wants to set a reminder, use "set_reminder".
13. For general compliance questions not about specific data, use "general_question" with the user's question as "question" param.
14. If an entity name is mentioned, include it as "entity_name" param. If an entity ID from context, use "entity_id".
15. If the user references "it" or "this entity" or "this document", use the context entity_id/document_id.
16. "upload_document" - Upload a new document. Use when user wants to upload, add, or submit a document file.
17. "replace_document" - Replace an existing document with a new version. Use when user wants to replace, swap, or update a document file.
18. "run_full_gap_analysis" - Run comprehensive compliance risk analysis for an entity. Use for "risk analysis", "full gap analysis", "comprehensive compliance check".

Return ONLY a JSON object:
{{
    "tool": "tool_name",
    "parameters": {{"key": "value"}},
    "reasoning": "brief explanation"
}}"""


async def classify_intent(message: str, conversation_history: list, context: dict) -> dict:
    """Classify user intent using Gemini (local or via n8n) with keyword fallback."""
    # Try 0: Quick keyword match for obvious patterns (upload, replace, risk analysis)
    msg_lower = message.lower()
    if "upload" in msg_lower and ("document" in msg_lower or "file" in msg_lower):
        if "replace" not in msg_lower and "swap" not in msg_lower:
            return {"tool": "upload_document", "parameters": {}, "reasoning": "quick keyword: upload"}
    if ("replace" in msg_lower or "swap" in msg_lower) and ("document" in msg_lower or "file" in msg_lower or ".pdf" in msg_lower):
        return {"tool": "replace_document", "parameters": {}, "reasoning": "quick keyword: replace"}
    if any(w in msg_lower for w in ["risk analysis", "full gap analysis", "full analysis", "comprehensive gap", "run analysis"]):
        return {"tool": "run_full_gap_analysis", "parameters": {"entity_id": context.get("entity_id", "")}, "reasoning": "quick keyword: risk analysis"}

    prompt = _build_classification_prompt(message, conversation_history, context)

    # Try 1: Local Gemini
    try:
        response = chat_completion(
            [{"role": "user", "content": prompt}],
            None,
        )
        if response and not response.startswith("Based on the compliance"):
            return _parse_json_response(response)
    except Exception as e:
        logger.warning("Local Gemini classification failed: %s", e)

    # Try 2: n8n Copilot Agent for classification
    try:
        n8n_result = await trigger_copilot_agent(
            query=f"CLASSIFY ONLY - return JSON with tool and parameters: {prompt}",
            context="Intent classification mode. Return ONLY a JSON object.",
        )
        if n8n_result.get("status") == "ok" and n8n_result.get("response"):
            parsed = _parse_json_response(n8n_result["response"])
            if parsed.get("tool") != "general_question" or parsed.get("reasoning") != "failed to parse":
                return parsed
    except Exception as e:
        logger.warning("n8n classification failed: %s", e)

    # Try 3: Keyword-based fallback
    return _fallback_classify(message, context)


def _parse_json_response(text: str) -> dict:
    """Extract JSON from Gemini response, handling markdown fences."""
    if not text:
        return {"tool": "general_question", "parameters": {"question": ""}, "reasoning": "empty response"}

    # Strip markdown code fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n", 1)
        if len(lines) > 1:
            cleaned = lines[1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # Try to find JSON object in the text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON within the text using regex
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {"tool": "general_question", "parameters": {"question": text}, "reasoning": "failed to parse"}


def _fallback_classify(message: str, context: dict) -> dict:
    """Keyword-based fallback when Gemini classification fails."""
    msg_lower = message.lower()

    # Check for specific patterns
    if any(w in msg_lower for w in ["search document", "find document", "list document", "show document"]):
        query = message
        for prefix in ["search for", "find", "search", "list", "show me", "show"]:
            if msg_lower.startswith(prefix):
                query = message[len(prefix):].strip()
                break
        return {"tool": "search_documents", "parameters": {"query": query}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["expir", "renewal", "renew", "due soon", "overdue"]):
        days = 30
        for d in [7, 14, 30, 60, 90]:
            if str(d) in msg_lower:
                days = d
                break
        return {"tool": "get_expiring_documents", "parameters": {"days": days}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["analyz", "gap analysis", "compliance gaps", "run analysis"]):
        if context.get("document_id"):
            return {"tool": "analyze_document", "parameters": {"document_id": context["document_id"]}, "reasoning": "keyword match with context"}
        if context.get("entity_id"):
            return {"tool": "get_compliance_gaps", "parameters": {"entity_id": context["entity_id"]}, "reasoning": "keyword match with context"}
        return {"tool": "general_question", "parameters": {"question": message}, "reasoning": "keyword match fallback"}

    if any(w in msg_lower for w in ["score", "compliance score", "rating", "grade"]):
        entity_id = context.get("entity_id", "")
        return {"tool": "get_compliance_score", "parameters": {"entity_id": entity_id}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["compare", "benchmark", "versus", "vs"]):
        return {"tool": "compare_entities", "parameters": {"entity_ids": []}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["list entities", "show entities", "all entities", "list vendors", "show vendors", "all vendors", "list properties", "show properties"]):
        return {"tool": "list_entities", "parameters": {}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["analytics", "dashboard", "summary", "overview", "report"]):
        metric_type = "summary"
        if "trend" in msg_lower:
            metric_type = "trends"
        elif "risk" in msg_lower and "matrix" in msg_lower:
            metric_type = "risk_matrix"
        elif "expir" in msg_lower or "forecast" in msg_lower:
            metric_type = "expiry_forecast"
        return {"tool": "get_analytics", "parameters": {"metric_type": metric_type}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["create entity", "new entity", "add entity", "create vendor", "new vendor", "add vendor", "create property", "new property", "add property"]):
        return {"tool": "create_entity", "parameters": {"name": ""}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["remind", "set reminder", "schedule", "alert me"]):
        return {"tool": "set_reminder", "parameters": {"title": message}, "reasoning": "keyword match"}

    if any(w in msg_lower for w in ["gap", "missing", "compliance gap"]):
        entity_id = context.get("entity_id", "")
        return {"tool": "get_compliance_gaps", "parameters": {"entity_id": entity_id}, "reasoning": "keyword match"}

    # Upload / Replace (check BEFORE general patterns)
    if "replace" in msg_lower or "swap" in msg_lower or "new version" in msg_lower:
        if "document" in msg_lower or "file" in msg_lower or ".pdf" in msg_lower:
            return {"tool": "replace_document", "parameters": {}, "reasoning": "keyword: replace"}
    if "upload" in msg_lower or ("add" in msg_lower and "document" in msg_lower) or "submit" in msg_lower:
        if "document" in msg_lower or "file" in msg_lower or ".pdf" in msg_lower:
            return {"tool": "upload_document", "parameters": {}, "reasoning": "keyword: upload"}
    # Full risk analysis
    if any(w in msg_lower for w in ["risk analysis", "full analysis", "comprehensive gap", "run analysis", "full gap analysis", "full risk"]):
        return {"tool": "run_full_gap_analysis", "parameters": {"entity_id": context.get("entity_id", "")}, "reasoning": "keyword: risk analysis"}

    # Default to general question
    return {"tool": "general_question", "parameters": {"question": message}, "reasoning": "no keyword match"}


# ===================================================================
# SUGGESTED ACTIONS GENERATOR
# ===================================================================

def generate_suggestions(tool_used: str, result: dict, context: dict) -> list:
    """Generate follow-up action suggestions based on the tool result."""
    suggestions = []
    data = result.get("data", {})
    data_type = data.get("type", "")

    if tool_used == "search_documents" and data.get("rows"):
        first_doc = data["rows"][0]
        suggestions.append({
            "label": f"Analyze '{first_doc.get('name', 'document')[:30]}'",
            "action": "analyze_document",
            "params": {"document_id": first_doc["id"]},
        })
        if first_doc.get("entity_id"):
            suggestions.append({
                "label": f"View entity details",
                "action": "get_entity_info",
                "params": {"entity_id": first_doc["entity_id"]},
            })

    elif tool_used == "get_document_details":
        doc = data.get("document", {})
        if doc.get("id"):
            suggestions.append({
                "label": "Run compliance analysis",
                "action": "analyze_document",
                "params": {"document_id": doc["id"]},
            })
        if doc.get("entity_id"):
            suggestions.append({
                "label": "View entity info",
                "action": "get_entity_info",
                "params": {"entity_id": doc["entity_id"]},
            })

    elif tool_used == "analyze_document":
        suggestions.append({
            "label": "View all compliance gaps",
            "action": "get_compliance_gaps",
            "params": {"entity_id": context.get("entity_id", "")},
        })
        suggestions.append({
            "label": "Compare with other entities",
            "action": "compare_entities",
            "params": {},
        })

    elif tool_used == "get_entity_info":
        entity = data.get("entity", {})
        eid = entity.get("id", "")
        suggestions.append({
            "label": "View compliance gaps",
            "action": "get_compliance_gaps",
            "params": {"entity_id": eid},
        })
        suggestions.append({
            "label": "View score breakdown",
            "action": "get_compliance_score",
            "params": {"entity_id": eid},
        })
        suggestions.append({
            "label": "Compare with other entities",
            "action": "compare_entities",
            "params": {},
        })

    elif tool_used == "list_entities":
        suggestions.append({
            "label": "View risk matrix",
            "action": "get_analytics",
            "params": {"metric_type": "risk_matrix"},
        })
        suggestions.append({
            "label": "Compare all entities",
            "action": "compare_entities",
            "params": {},
        })

    elif tool_used == "get_compliance_score":
        suggestions.append({
            "label": "View compliance gaps",
            "action": "get_compliance_gaps",
            "params": {"entity_id": context.get("entity_id", "")},
        })
        suggestions.append({
            "label": "View expiring documents",
            "action": "get_expiring_documents",
            "params": {"days": 30},
        })

    elif tool_used == "get_analytics":
        if data_type == "analytics_summary":
            suggestions.append({
                "label": "View risk matrix",
                "action": "get_analytics",
                "params": {"metric_type": "risk_matrix"},
            })
            suggestions.append({
                "label": "View expiry forecast",
                "action": "get_analytics",
                "params": {"metric_type": "expiry_forecast"},
            })
        elif data_type == "risk_matrix":
            suggestions.append({
                "label": "View dashboard summary",
                "action": "get_analytics",
                "params": {"metric_type": "summary"},
            })

    elif tool_used == "get_expiring_documents":
        suggestions.append({
            "label": "Set renewal reminders",
            "action": "set_reminder",
            "params": {"title": "Document renewal reminder"},
        })
        suggestions.append({
            "label": "View analytics summary",
            "action": "get_analytics",
            "params": {"metric_type": "summary"},
        })

    elif tool_used == "compare_entities":
        worst = data.get("worst", {})
        if worst and worst.get("entity_id"):
            suggestions.append({
                "label": f"View gaps for {worst.get('name', 'lowest scorer')[:25]}",
                "action": "get_compliance_gaps",
                "params": {"entity_id": worst["entity_id"]},
            })

    elif tool_used == "get_compliance_gaps":
        suggestions.append({
            "label": "View expiring documents",
            "action": "get_expiring_documents",
            "params": {"days": 30},
        })
        suggestions.append({
            "label": "Search all documents",
            "action": "search_documents",
            "params": {"entity_id": context.get("entity_id", "")},
        })

    # Always offer a general fallback if few suggestions
    if len(suggestions) < 2:
        suggestions.append({
            "label": "View dashboard summary",
            "action": "get_analytics",
            "params": {"metric_type": "summary"},
        })

    return suggestions[:3]


# ===================================================================
# CONVERSATION MANAGEMENT
# ===================================================================

async def _generate_title(message: str) -> str:
    """Generate a short conversation title from the first message using Gemini."""
    try:
        prompt = (
            f"Generate a very short title (3-6 words, no quotes) for a conversation "
            f"that starts with this message: \"{message[:200]}\"\n\nTitle:"
        )
        title = chat_completion([{"role": "user", "content": prompt}], None)
        # Clean up
        title = title.strip().strip('"\'').strip()
        if len(title) > 60:
            title = title[:57] + "..."
        return title or message[:40]
    except Exception:
        return message[:40]


def _get_conversation(conversation_id: str) -> Optional[dict]:
    """Load a conversation from Firestore."""
    try:
        return get_document(CONVERSATIONS_COLLECTION, conversation_id)
    except Exception:
        return None


def _save_conversation(conversation_id: str, data: dict):
    """Save/update conversation in Firestore."""
    try:
        existing = get_document(CONVERSATIONS_COLLECTION, conversation_id)
        if existing:
            update_document(CONVERSATIONS_COLLECTION, conversation_id, data)
        else:
            create_document(CONVERSATIONS_COLLECTION, data, doc_id=conversation_id)
    except Exception as e:
        print(f"Warning: Failed to save conversation: {e}")


# ===================================================================
# MAIN AGENT PIPELINE
# ===================================================================

async def _run_agent(message: str, conversation: dict, context: dict, user: dict) -> dict:
    """
    Main agent pipeline:
    1. Classify intent
    2. Execute tool
    3. Format response
    4. Generate suggestions
    """
    history = conversation.get("messages", [])
    user_id = user.get("user_id", user.get("email", ""))

    # Get relevant memories
    memories = _get_relevant_memories(user_id, message)
    memory_context = ""
    if memories:
        memory_lines = [f"- [{m.get('memory_type', 'fact')}] {m.get('content', '')}" for m in memories[:8]]
        memory_context = "\nUser memories (long-term context):\n" + "\n".join(memory_lines)

    # Merge persistent context with request context
    merged_context = {**(conversation.get("context", {})), **(context or {})}

    # Step 1: Classify intent (with memory context appended)
    message_with_memory = message + memory_context if memory_context else message
    classification = await classify_intent(message_with_memory, history, merged_context)
    tool_name = classification.get("tool", "general_question")
    params = classification.get("parameters", {})

    # Ensure question param for general_question
    if tool_name == "general_question" and "question" not in params:
        params["question"] = message

    # Step 2: Execute tool
    tool_def = AGENT_TOOLS.get(tool_name)
    if not tool_def:
        tool_def = AGENT_TOOLS["general_question"]
        params = {"question": message}

    try:
        result = await tool_def["function"](params, user)
    except Exception as e:
        print(f"Tool execution error ({tool_name}): {e}")
        traceback.print_exc()
        result = {
            "message": f"I encountered an error while processing your request. Please try again or rephrase your question.",
            "data": {"type": "error", "error": str(e)},
        }

    # Step 3: Update context based on result
    result_data = result.get("data", {})
    if result_data.get("type") == "entity_card":
        entity = result_data.get("entity", {})
        if entity.get("id"):
            merged_context["entity_id"] = entity["id"]
            merged_context["entity_name"] = entity.get("name", "")
    elif result_data.get("type") == "document_card":
        doc = result_data.get("document", {})
        if doc.get("id"):
            merged_context["document_id"] = doc["id"]
            merged_context["document_name"] = doc.get("name", "")
            if doc.get("entity_id"):
                merged_context["entity_id"] = doc["entity_id"]

    # Step 4: Generate suggestions
    suggestions = generate_suggestions(tool_name, result, merged_context)

    # Extract memories in background (don't block response)
    import asyncio
    conversation_id = conversation.get("id", "")
    asyncio.create_task(_extract_memories(message, result.get("message", ""), user_id, conversation_id))

    return {
        "message": result.get("message", ""),
        "data": result.get("data"),
        "sources": result.get("sources", []),
        "suggested_actions": suggestions,
        "context": merged_context,
        "_tool": tool_name,
        "_classification": classification.get("reasoning", ""),
    }


# ===================================================================
# NEW AGENT ENDPOINTS
# ===================================================================

@router.post("/chat")
async def copilot_chat(body: CopilotRequest, user: dict = Depends(get_current_user)):
    """Main AI copilot agent endpoint.

    Accepts a message, classifies intent, executes the appropriate tool,
    and returns a structured response with suggested follow-up actions.
    """
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    conversation_id = body.conversation_id or str(uuid.uuid4())
    context = body.context or {}

    # Load or create conversation
    conversation = _get_conversation(conversation_id)
    if not conversation:
        conversation = {
            "user_id": user.get("user_id", user.get("email", "")),
            "title": "",
            "messages": [],
            "message_count": 0,
            "context": {},
        }

    # Add user message
    now_iso = datetime.now(timezone.utc).isoformat()
    conversation["messages"].append({
        "role": "user",
        "content": message,
        "timestamp": now_iso,
    })

    # Run agent pipeline
    agent_result = await _run_agent(message, conversation, context, user)

    # Add assistant message
    assistant_msg = {
        "role": "assistant",
        "content": agent_result["message"],
        "data": agent_result.get("data"),
        "sources": agent_result.get("sources", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    conversation["messages"].append(assistant_msg)

    # Cap conversation length
    if len(conversation["messages"]) > MAX_CONVERSATION_MESSAGES:
        conversation["messages"] = conversation["messages"][-MAX_CONVERSATION_MESSAGES:]

    # Update context
    conversation["context"] = agent_result.get("context", context)
    conversation["message_count"] = len(conversation["messages"])
    conversation["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Auto-generate title for new conversations
    if not conversation.get("title"):
        conversation["title"] = await _generate_title(message)

    # Save conversation
    _save_conversation(conversation_id, conversation)

    return CopilotResponse(
        message=agent_result["message"],
        data=agent_result.get("data"),
        sources=agent_result.get("sources", []),
        conversation_id=conversation_id,
        suggested_actions=agent_result.get("suggested_actions", []),
    )


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    """List user's copilot conversations, ordered by most recent."""
    user_id = user.get("user_id", user.get("email", ""))

    try:
        convos = get_documents(
            CONVERSATIONS_COLLECTION,
            filters=[("user_id", "==", user_id)],
            order_by="updated_at",
            direction="DESCENDING",
            limit=50,
        )
    except Exception:
        convos = []

    result = []
    for c in convos:
        messages = c.get("messages", [])
        last_msg = messages[-1].get("content", "")[:100] if messages else ""
        result.append({
            "id": c.get("id", ""),
            "title": c.get("title", "Untitled"),
            "last_message": last_msg,
            "updated_at": c.get("updated_at", ""),
            "created_at": c.get("created_at", ""),
            "message_count": c.get("message_count", len(messages)),
        })

    return {"conversations": result, "total": len(result)}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """Get full conversation history."""
    convo = _get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify ownership
    user_id = user.get("user_id", user.get("email", ""))
    if convo.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "id": convo.get("id", conversation_id),
        "title": convo.get("title", "Untitled"),
        "messages": convo.get("messages", []),
        "context": convo.get("context", {}),
        "created_at": convo.get("created_at", ""),
        "updated_at": convo.get("updated_at", ""),
        "message_count": convo.get("message_count", 0),
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """Delete a conversation."""
    convo = _get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = user.get("user_id", user.get("email", ""))
    if convo.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        delete_document(CONVERSATIONS_COLLECTION, conversation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")

    return {"message": "Conversation deleted", "id": conversation_id}


@router.post("/conversations/{conversation_id}/title")
async def rename_conversation(
    conversation_id: str,
    body: ConversationTitleRequest,
    user: dict = Depends(get_current_user),
):
    """Rename a conversation."""
    convo = _get_conversation(conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = user.get("user_id", user.get("email", ""))
    if convo.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        update_document(CONVERSATIONS_COLLECTION, conversation_id, {"title": body.title})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename: {str(e)}")

    return {"message": "Conversation renamed", "id": conversation_id, "title": body.title}


# ===================================================================
# BACKWARD-COMPATIBLE LEGACY ENDPOINTS
# ===================================================================

@router.post("/query")
async def copilot_query(body: CopilotQuery, user: dict = Depends(get_current_user)):
    """RAG-powered compliance query (legacy endpoint).

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
        for msg in body.conversation_history[-10:]:
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
async def analyze_document_legacy(body: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """Analyze a specific document using AI (legacy endpoint)."""
    doc = None
    try:
        doc = get_document("documents", body.document_id)
    except Exception:
        pass

    if not doc:
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
    """Get AI-powered compliance suggestions for an entity (legacy endpoint)."""
    entity_id = body.entity_id
    breakdown = get_score_breakdown(entity_id)

    suggestions = []
    for rec in breakdown.get("recommendations", []):
        suggestions.append({
            "priority": rec.get("priority", "medium"),
            "category": rec.get("category", "general"),
            "suggestion": rec.get("message", ""),
            "impact": "Improves overall compliance score",
        })

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


# ===================================================================
# MEMORY ENDPOINTS
# ===================================================================

@router.get("/memory")
async def list_memories(user: dict = Depends(get_current_user)):
    """List all user memories."""
    user_id = user.get("user_id", user.get("email", ""))
    memories = get_documents(MEMORY_COLLECTION,
        filters=[("user_id", "==", user_id)],
        limit=100)
    return {"memories": memories, "total": len(memories)}


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, user: dict = Depends(get_current_user)):
    """Delete a specific memory."""
    mem = get_document(MEMORY_COLLECTION, memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    user_id = user.get("user_id", user.get("email", ""))
    if mem.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    delete_document(MEMORY_COLLECTION, memory_id)
    return {"message": "Memory deleted", "id": memory_id}


# ===================================================================
# COPILOT UPLOAD ENDPOINT
# ===================================================================

@router.post("/upload")
async def copilot_upload(
    file: UploadFile = File(...),
    action: str = Form("upload"),
    entity_name: str = Form(""),
    document_type: str = Form(""),
    document_id: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """Handle document upload/replace from copilot chat."""
    try:
        file_data = await file.read()
        filename = file.filename or "document.pdf"
        content_type = file.content_type or "application/pdf"
        org_id = user.get("org_id", "")

        if action == "replace" and document_id:
            # Archive old document
            old_doc = get_document("documents", document_id)
            if old_doc:
                update_document("documents", document_id, {"status": "archived"})
                entity_id = old_doc.get("entity_id", "")
                entity_name = entity_name or old_doc.get("entity_name", "")
                document_type = document_type or old_doc.get("document_type", "")
            else:
                entity_id = ""
        else:
            # Resolve entity for new upload
            entity_id = ""
            if entity_name:
                try:
                    entities = get_documents("entities", limit=100)
                    for e in entities:
                        if entity_name.lower() in e.get("name", "").lower():
                            entity_id = e.get("id", "")
                            break
                    if not entity_id:
                        entity_id = create_document("entities", {
                            "name": entity_name,
                            "entity_type": "vendor",
                            "compliance_score": 0,
                            "risk_level": "medium",
                            "document_count": 0,
                        })
                except Exception:
                    pass

        # Create document record
        new_doc_id = create_document("documents", {
            "name": filename,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "document_type": document_type or "General",
            "status": "processing",
            "uploaded_by": user.get("email", ""),
            "organization_id": org_id,
            "file_size": len(file_data),
            "content_type": content_type,
        })

        # Trigger n8n document intake
        try:
            n8n_result = await trigger_document_intake(
                document_id=new_doc_id,
                filename=filename,
                content_type=content_type,
                entity_id=entity_id,
                document_type=document_type or "General",
                organization_id=org_id,
                file_data=file_data,
            )

            # Update with AI data if available
            if n8n_result and n8n_result.get("status") != "demo":
                ai_update = {}
                for field in ["ai_summary", "key_clauses", "risk_flags", "parties",
                             "compliance_requirements", "extracted_content", "jurisdiction",
                             "party_a", "party_b", "effective_date", "expiry_date",
                             "document_type_detected", "document_name"]:
                    if field in n8n_result:
                        ai_update[field] = n8n_result[field]
                if ai_update:
                    ai_update["status"] = "active"
                    update_document("documents", new_doc_id, ai_update)
        except Exception as e:
            logger.warning(f"n8n document intake failed: {e}")
            update_document("documents", new_doc_id, {"status": "active"})

        return {
            "message": f"Document **{filename}** uploaded successfully!",
            "data": {
                "type": "document_card",
                "document": {
                    "id": new_doc_id,
                    "name": filename,
                    "document_type": document_type or "General",
                    "entity_name": entity_name,
                    "status": "processing",
                    "score": 0,
                },
            },
        }
    except Exception as e:
        logger.warning(f"Copilot upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
