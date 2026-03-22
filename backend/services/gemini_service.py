"""ComplyChip V3 - Google Gemini AI Service"""
from __future__ import annotations

import json
from typing import Optional

from backend.config import GEMINI_API_KEY

_genai = None
_model = None
_embed_model = None


def _init_gemini():
    """Lazily initialize the Gemini client."""
    global _genai, _model, _embed_model
    if _genai is not None:
        return True
    if not GEMINI_API_KEY:
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _genai = genai
        _model = genai.GenerativeModel("gemini-1.5-flash")
        _embed_model = "models/embedding-001"
        return True
    except Exception as e:
        print(f"Warning: Gemini initialization failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def generate_embeddings(text: str) -> list:
    """Generate embedding vector for the given text.

    Returns a list of floats (768-dim by default).
    Falls back to a zero vector when Gemini is not configured.
    """
    if not _init_gemini():
        return [0.0] * 768  # demo fallback

    try:
        result = _genai.embed_content(
            model=_embed_model,
            content=text,
            task_type="retrieval_document",
        )
        return result["embedding"]
    except Exception as e:
        print(f"Warning: Embedding generation failed: {e}")
        return [0.0] * 768


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """Analyze the following document text and extract structured metadata.
Return a JSON object with these keys:
- parties: list of party names mentioned
- dates: list of important dates (ISO format when possible)
- amounts: list of monetary amounts mentioned
- jurisdiction: the legal jurisdiction
- clauses: list of clause summaries (title + brief description)
- summary: a 2-3 sentence summary of the document
- doc_type_detected: best guess at document type

Document type hint: {doc_type}

--- DOCUMENT TEXT ---
{text}
"""


def extract_metadata(text: str, doc_type: str = "unknown") -> dict:
    """Use Gemini to extract structured metadata from document text.

    Returns a dict with parties, dates, amounts, jurisdiction, clauses, summary.
    Falls back to sample metadata when Gemini is not configured.
    """
    if not _init_gemini():
        return _demo_metadata(doc_type)

    try:
        prompt = _EXTRACT_PROMPT.format(doc_type=doc_type, text=text[:15000])
        response = _model.generate_content(prompt)
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw)
    except Exception as e:
        print(f"Warning: Metadata extraction failed: {e}")
        return _demo_metadata(doc_type)


def _demo_metadata(doc_type: str) -> dict:
    return {
        "parties": ["Acme Corp", "ComplyChip Inc"],
        "dates": ["2025-01-15", "2026-01-15"],
        "amounts": ["$50,000"],
        "jurisdiction": "State of California",
        "clauses": [
            {"title": "Confidentiality", "description": "Standard mutual NDA clause"},
            {"title": "Term", "description": "12-month initial term with auto-renewal"},
            {"title": "Governing Law", "description": "California state law"},
        ],
        "summary": f"This {doc_type} document outlines the agreement between two parties with standard compliance terms.",
        "doc_type_detected": doc_type,
    }


# ---------------------------------------------------------------------------
# Chat / RAG completion
# ---------------------------------------------------------------------------

_CHAT_SYSTEM = """You are ComplyChip AI, a compliance intelligence assistant.
Answer questions using the provided context documents. Be precise and cite
document names when possible. If you are unsure, say so.

Context documents:
{context}
"""


def chat_completion(messages: list, context_docs: Optional[list] = None) -> str:
    """Generate a chat completion with optional RAG context.

    messages: list of dicts with 'role' and 'content' keys.
    context_docs: optional list of document dicts for RAG.
    Returns the assistant response string.
    """
    if not _init_gemini():
        return _demo_chat_response(messages)

    try:
        context_str = ""
        if context_docs:
            for doc in context_docs[:5]:
                context_str += f"\n--- {doc.get('name', 'Document')} ---\n{doc.get('text', '')[:3000]}\n"
        system = _CHAT_SYSTEM.format(context=context_str if context_str else "No context documents provided.")

        chat_history = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            chat_history.append({"role": role, "parts": [msg["content"]]})

        chat = _model.start_chat(history=chat_history[:-1])
        last_msg = chat_history[-1]["parts"][0] if chat_history else "Hello"
        full_prompt = f"{system}\n\nUser question: {last_msg}"
        response = chat.send_message(full_prompt)
        return response.text
    except Exception as e:
        print(f"Warning: Chat completion failed: {e}")
        return _demo_chat_response(messages)


def _demo_chat_response(messages: list) -> str:
    last = messages[-1]["content"] if messages else ""
    return (
        f"Based on the compliance documents in your portfolio, here is my analysis "
        f"regarding your query about '{last[:80]}': The relevant regulations suggest "
        f"maintaining up-to-date documentation, ensuring all certificates are within "
        f"their validity period, and conducting regular vendor risk assessments. "
        f"I recommend reviewing the expiring documents in your dashboard for immediate action items."
    )


# ---------------------------------------------------------------------------
# Compliance gap analysis
# ---------------------------------------------------------------------------

_GAP_PROMPT = """Analyze the following document data against the compliance rules.
Identify compliance gaps where the document does not meet the rule requirements.

Return a JSON array of gap objects with keys:
- rule_id: the rule identifier
- rule_name: name of the rule
- severity: "critical", "high", "medium", or "low"
- description: what is missing or non-compliant
- recommendation: how to remediate

Document data: {doc_data}

Compliance rules: {rules}
"""


def analyze_compliance_gaps(doc_data: dict, rules: list) -> list:
    """Analyze document data against compliance rules and return gaps.

    Falls back to sample gaps when Gemini is not configured.
    """
    if not _init_gemini():
        return _demo_gaps()

    try:
        prompt = _GAP_PROMPT.format(
            doc_data=json.dumps(doc_data)[:5000],
            rules=json.dumps(rules)[:5000],
        )
        response = _model.generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw)
    except Exception as e:
        print(f"Warning: Gap analysis failed: {e}")
        return _demo_gaps()


def _demo_gaps() -> list:
    return [
        {
            "rule_id": "REG-001",
            "rule_name": "Insurance Certificate Validity",
            "severity": "critical",
            "description": "General liability insurance certificate has expired.",
            "recommendation": "Request updated certificate of insurance from the vendor immediately.",
        },
        {
            "rule_id": "REG-005",
            "rule_name": "Data Processing Agreement",
            "severity": "high",
            "description": "No Data Processing Agreement on file for vendors handling PII.",
            "recommendation": "Execute a DPA with the vendor before continuing data sharing.",
        },
        {
            "rule_id": "REG-012",
            "rule_name": "Safety Training Records",
            "severity": "medium",
            "description": "Safety training certifications are older than 12 months.",
            "recommendation": "Schedule refresher safety training for all on-site personnel.",
        },
    ]


# ---------------------------------------------------------------------------
# Clause anomaly detection
# ---------------------------------------------------------------------------

_ANOMALY_PROMPT = """Compare the following contract clauses against the standard clauses.
Identify anomalies, unusual terms, or deviations. Score each on a 0-1 scale.

Return a JSON array of objects with keys:
- clause_title: name of the clause
- anomaly_score: float 0.0 (normal) to 1.0 (highly anomalous)
- description: what is unusual
- risk_level: "low", "medium", "high"

Contract clauses: {clauses}

Standard clauses: {standard_clauses}
"""


def detect_clause_anomalies(clauses: list, standard_clauses: list) -> list:
    """Detect anomalies in contract clauses compared to standards.

    Falls back to sample anomalies when Gemini is not configured.
    """
    if not _init_gemini():
        return _demo_anomalies()

    try:
        prompt = _ANOMALY_PROMPT.format(
            clauses=json.dumps(clauses)[:5000],
            standard_clauses=json.dumps(standard_clauses)[:5000],
        )
        response = _model.generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw)
    except Exception as e:
        print(f"Warning: Anomaly detection failed: {e}")
        return _demo_anomalies()


def _demo_anomalies() -> list:
    return [
        {
            "clause_title": "Limitation of Liability",
            "anomaly_score": 0.85,
            "description": "Liability cap is significantly lower than industry standard at 1x annual fees.",
            "risk_level": "high",
        },
        {
            "clause_title": "Indemnification",
            "anomaly_score": 0.62,
            "description": "One-sided indemnification favoring the vendor without mutual coverage.",
            "risk_level": "medium",
        },
        {
            "clause_title": "Termination",
            "anomaly_score": 0.30,
            "description": "Standard 30-day notice period, slightly below typical 60-day window.",
            "risk_level": "low",
        },
    ]
