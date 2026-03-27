"""ComplyChip V3 - n8n Workflow Client"""
from __future__ import annotations

from typing import Optional

from backend.config import (
    N8N_BASE_URL,
    N8N_DOCUMENT_INTAKE_WEBHOOK,
    N8N_COMPLIANCE_EVAL_WEBHOOK,
    N8N_SEND_REMINDER_WEBHOOK,
    N8N_VENDOR_ENRICHMENT_WEBHOOK,
    N8N_RISK_ANALYSIS_WEBHOOK,
    N8N_CLAUSE_ANOMALY_WEBHOOK,
    N8N_COPILOT_AGENT_WEBHOOK,
    N8N_REPLACE_DOCUMENT_WEBHOOK,
)

# Map friendly workflow names to webhook URLs
_WORKFLOW_MAP = {
    "document-intake": N8N_DOCUMENT_INTAKE_WEBHOOK,
    "compliance-evaluation": N8N_COMPLIANCE_EVAL_WEBHOOK,
    "send-reminder": N8N_SEND_REMINDER_WEBHOOK,
    "vendor-enrichment": N8N_VENDOR_ENRICHMENT_WEBHOOK,
    "risk-analysis": N8N_RISK_ANALYSIS_WEBHOOK,
    "clause-anomaly": N8N_CLAUSE_ANOMALY_WEBHOOK,
    "copilot-agent": N8N_COPILOT_AGENT_WEBHOOK,
    "replace-document": N8N_REPLACE_DOCUMENT_WEBHOOK,
}


async def trigger_workflow(workflow_name: str, payload: dict) -> dict:
    """Trigger an n8n workflow by name.

    workflow_name: one of the keys in _WORKFLOW_MAP or a full URL.
    payload: JSON-serializable dict to POST.
    Returns the JSON response from n8n, or a demo response on failure.
    """
    url = _WORKFLOW_MAP.get(workflow_name, workflow_name)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Warning: n8n workflow '{workflow_name}' trigger failed: {e}")
        return {
            "status": "demo",
            "message": f"Workflow '{workflow_name}' triggered (demo mode)",
            "workflow": workflow_name,
            "payload_received": True,
        }


# ---------------------------------------------------------------------------
# Named convenience methods
# ---------------------------------------------------------------------------

async def trigger_document_intake(
    document_id: str,
    filename: str,
    content_type: str,
    entity_id: str,
    document_type: str,
    organization_id: str = "",
    file_data: bytes = b"",
) -> dict:
    """Trigger the document intake / processing workflow.

    Sends the file as multipart with metadata as query parameters.
    n8n handles Gemini analysis and Firestore update.
    """
    base_url = _WORKFLOW_MAP.get("document-intake", N8N_DOCUMENT_INTAKE_WEBHOOK)

    # Pass metadata as query params so n8n can access them reliably
    params = {
        "document_id": document_id,
        "filename": filename,
        "content_type": content_type,
        "entity_id": entity_id,
        "document_type": document_type,
        "organization_id": organization_id,
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=180.0) as client:
            files = {"data": (filename, file_data, content_type)}
            resp = await client.post(base_url, params=params, files=files)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Warning: n8n workflow 'document-intake' trigger failed: {e}")
        return {
            "status": "demo",
            "message": "Document intake triggered (demo mode)",
            "workflow": "document-intake",
            "payload_received": True,
        }


async def trigger_compliance_evaluation(
    entity_id: str,
    organization_id: str = "",
    force_recalculate: bool = False,
) -> dict:
    """Trigger compliance evaluation for an entity."""
    return await trigger_workflow("compliance-evaluation", {
        "entity_id": entity_id,
        "organization_id": organization_id,
        "force_recalculate": force_recalculate,
    })


async def trigger_send_reminder(
    recipient_email: str,
    subject: str,
    body: str,
    entity_id: str = "",
    document_id: str = "",
    reminder_type: str = "expiry",
    organization_id: str = "",
) -> dict:
    """Trigger the send-reminder workflow."""
    return await trigger_workflow("send-reminder", {
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "entity_id": entity_id,
        "document_id": document_id,
        "reminder_type": reminder_type,
        "organization_id": organization_id,
    })


async def trigger_vendor_enrichment(
    vendor_id: str,
    vendor_name: str,
    organization_id: str = "",
) -> dict:
    """Trigger vendor data enrichment workflow."""
    return await trigger_workflow("vendor-enrichment", {
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "organization_id": organization_id,
    })


async def trigger_risk_analysis(
    entity_id: str,
    document_ids: Optional[list] = None,
    organization_id: str = "",
) -> dict:
    """Trigger risk analysis workflow."""
    return await trigger_workflow("risk-analysis", {
        "entity_id": entity_id,
        "document_ids": document_ids or [],
        "organization_id": organization_id,
    })


async def trigger_clause_anomaly(
    document_id: str,
    clauses: Optional[list] = None,
    organization_id: str = "",
) -> dict:
    """Trigger clause anomaly detection workflow."""
    return await trigger_workflow("clause-anomaly", {
        "document_id": document_id,
        "clauses": clauses or [],
        "organization_id": organization_id,
    })


async def trigger_copilot_agent(
    query: str,
    context: str = "",
    conversation_history: Optional[list] = None,
) -> dict:
    """Trigger the Copilot Agent n8n workflow (Gemini + Pinecone + Firebase).

    This sends the user query to n8n which uses:
    - Gemini for AI reasoning
    - Pinecone vector store for RAG document search
    - Firebase Firestore for data access

    Returns: { response: str, sources: list, status: str }
    """
    import httpx

    url = _WORKFLOW_MAP.get("copilot-agent", N8N_COPILOT_AGENT_WEBHOOK)
    payload = {
        "query": query,
        "context": context,
        "conversation_history": conversation_history or [],
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Warning: Copilot agent workflow failed: {e}")
        return {
            "response": "",
            "status": "error",
            "error": str(e),
        }


async def trigger_replace_document(
    document_id: str, filename: str, content_type: str,
    entity_id: str, document_type: str, organization_id: str = "",
    file_data: bytes = b"",
) -> dict:
    """Trigger the replace-document n8n workflow."""
    url = N8N_REPLACE_DOCUMENT_WEBHOOK
    params = {
        "document_id": document_id,
        "filename": filename,
        "content_type": content_type,
        "entity_id": entity_id,
        "document_type": document_type,
        "organization_id": organization_id,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=180.0) as client:
            files = {"data": (filename, file_data, content_type)}
            resp = await client.post(url, params=params, files=files)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Warning: replace-document trigger failed: {e}")
        return {"status": "demo", "message": "Replace triggered (demo mode)"}
