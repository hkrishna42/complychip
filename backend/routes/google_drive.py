"""ComplyChip V3 - Google Drive Routes

Endpoints for Google Drive OAuth, folder/file browsing, and proxy upload
(download from Drive then feed into the existing n8n document-intake pipeline).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.dependencies import get_current_user
from backend.config import GCS_BUCKET
from backend.services.firestore_service import (
    create_document,
    update_document,
)
from backend.services.n8n_client import trigger_document_intake
from backend.services.google_drive_service import (
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    get_user_email,
    store_tokens,
    load_tokens,
    delete_tokens,
    get_valid_credentials,
    list_all_folders as drive_list_all_folders,
    list_files_in_folder as drive_list_files_in_folder,
    download_file as drive_download_file,
)
from backend.services.gcs_service import upload_file
from backend.routes.upload import (
    _resolve_entity_id,
    _compute_score,
    _index_to_pinecone,
    _update_entity_score,
)

router = APIRouter(tags=["Google Drive"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CallbackRequest(BaseModel):
    code: str
    redirect_uri: str


class ListFilesRequest(BaseModel):
    folder_id: str


class ProxyUploadRequest(BaseModel):
    file_id: str
    file_name: str
    entity_id: str = ""
    entity_name: str = ""
    document_type: str = "Other"
    expiry_date: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/auth-url")
async def auth_url(
    redirect_uri: str = "http://localhost:8000/google-drive/callback",
    user: dict = Depends(get_current_user),
):
    """Generate Google OAuth 2.0 authorization URL."""
    try:
        url, state = get_auth_url(redirect_uri)
        return {"auth_url": url, "state": state}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {e}")


@router.post("/callback")
async def callback(
    body: CallbackRequest,
    user: dict = Depends(get_current_user),
):
    """Exchange OAuth authorization code for tokens and store them."""
    org_id = user.get("org_id", "default")
    try:
        creds = exchange_code_for_credentials(body.code, body.redirect_uri)
        email = get_user_email(creds)
        store_tokens(org_id, creds, email=email)
        return {"success": True, "email": email}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {e}")


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    """Check whether Google Drive is connected for the current org."""
    org_id = user.get("org_id", "default")
    token_data = load_tokens(org_id)
    if token_data and token_data.get("refresh_token"):
        return {
            "connected": True,
            "email": token_data.get("email", ""),
        }
    return {"connected": False, "email": ""}


@router.get("/all-folders")
async def all_folders(user: dict = Depends(get_current_user)):
    """List all folders in the connected Google Drive."""
    org_id = user.get("org_id", "default")
    try:
        creds = get_valid_credentials(org_id)
        folders = drive_list_all_folders(creds)
        return {"folders": folders}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list folders: {e}")


@router.post("/list-files")
async def list_files(
    body: ListFilesRequest,
    user: dict = Depends(get_current_user),
):
    """List files in a specific Google Drive folder."""
    org_id = user.get("org_id", "default")
    try:
        creds = get_valid_credentials(org_id)
        files = drive_list_files_in_folder(creds, body.folder_id)
        return {"files": files}
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {e}")


@router.post("/proxy-upload")
async def proxy_upload(
    body: ProxyUploadRequest,
    user: dict = Depends(get_current_user),
):
    """Download a file from Google Drive and run it through the upload pipeline.

    This reuses the same n8n document-intake workflow as direct uploads:
    GCS upload -> Firestore doc -> n8n webhook -> AI analysis -> score update.
    """
    org_id = user.get("org_id", "default")

    # 1. Download file from Google Drive
    try:
        creds = get_valid_credentials(org_id)
        file_bytes, file_name = drive_download_file(creds, body.file_id, body.file_name)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download from Drive: {e}")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Downloaded file is empty")

    # 2. Resolve entity
    entity_name = body.entity_name or body.entity_id
    if not entity_name:
        raise HTTPException(status_code=400, detail="Entity name or ID is required")

    entity_id = body.entity_id
    if not entity_id or entity_id == entity_name:
        entity_id = _resolve_entity_id(entity_name, org_id)

    # Determine content type from file name
    lower_name = file_name.lower()
    if lower_name.endswith(".pdf"):
        content_type = "application/pdf"
    elif lower_name.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif lower_name.endswith(".png"):
        content_type = "image/png"
    else:
        content_type = "application/octet-stream"

    # 3. Upload to GCS (graceful fallback)
    gcs_path = f"documents/{entity_id}/{uuid.uuid4().hex[:8]}_{file_name}"
    try:
        actual_path = upload_file(file_bytes, file_name, content_type, entity_id)
        if actual_path and not actual_path.startswith("demo-"):
            gcs_path = actual_path
    except Exception as e:
        print(f"GCS upload failed (will continue): {e}")

    # 4. Create Firestore document record
    now = datetime.now(timezone.utc).isoformat()
    doc_data = {
        "name": file_name,
        "document_type": body.document_type,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "organization_id": org_id,
        "uploaded_by": user.get("user_id", ""),
        "upload_source": "google_drive",
        "google_drive_file_id": body.file_id,
        "status": "processing",
        "processing_status": "pending",
        "gcs_path": gcs_path,
        "gcs_bucket": GCS_BUCKET,
        "file_size": len(file_bytes),
        "content_type": content_type,
        "notes": body.notes,
        "score": 0,
        "compliance_status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    if body.expiry_date:
        doc_data["expiry_date"] = body.expiry_date

    try:
        doc_id = create_document("documents", doc_data)
    except Exception:
        doc_id = f"demo-doc-{uuid.uuid4().hex[:8]}"

    # 5. Trigger n8n AI pipeline (same as direct upload)
    n8n_response = {}
    try:
        n8n_response = await trigger_document_intake(
            document_id=doc_id or "unknown",
            filename=file_name,
            content_type=content_type,
            entity_id=entity_id,
            document_type=body.document_type,
            organization_id=org_id,
            file_data=file_bytes,
        )
        print(f"n8n response for Drive upload {doc_id}: success={n8n_response.get('success')}")

        # 6. Update Firestore with AI-extracted data
        if n8n_response.get("success") and doc_id:
            ai_update = {
                "status": "processed",
                "processing_status": "complete",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
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
                    key = "document_type_detected" if field == "document_type" else field
                    if key == "expiry_date" and body.expiry_date:
                        ai_update["ai_expiry_date"] = val
                        continue
                    ai_update[key] = val

            score = _compute_score(ai_update, body.expiry_date)
            ai_update["score"] = score
            ai_update["compliance_status"] = (
                "compliant" if score >= 80
                else "warning" if score >= 60
                else "non_compliant"
            )
            ai_update["pinecone_indexed"] = False

            try:
                update_document("documents", doc_id, ai_update)
                print(f"Firestore updated for Drive upload {doc_id}: score={score}")
                _update_entity_score(entity_id)
                _index_to_pinecone(doc_id, entity_id, org_id, body.document_type, ai_update)
            except Exception as e:
                print(f"Firestore update failed for {doc_id}: {e}")
    except Exception as e:
        print(f"n8n trigger failed for Drive upload {doc_id}: {e}")

    return {
        "document_id": doc_id or f"demo-doc-{uuid.uuid4().hex[:8]}",
        "filename": file_name,
        "gcs_path": gcs_path,
        "upload_source": "google_drive",
        "status": "processing" if not n8n_response.get("success") else "processed",
        "message": "Document imported from Google Drive. Background processing started.",
    }


@router.post("/disconnect")
async def disconnect(user: dict = Depends(get_current_user)):
    """Disconnect Google Drive by removing stored OAuth tokens."""
    org_id = user.get("org_id", "default")
    deleted = delete_tokens(org_id)
    if deleted:
        return {"success": True, "message": "Google Drive disconnected."}
    return {"success": True, "message": "No Google Drive connection found."}
