"""ComplyChip V3 - Google Drive Integration Service

Handles OAuth 2.0 authentication, token management, folder/file listing,
and file download from Google Drive.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from backend.services.firestore_service import (
    create_document,
    delete_document,
    get_document,
    update_document,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
TOKEN_COLLECTION = "google_drive_tokens"

# Client configuration (web app credentials)
_CLIENT_CONFIG: Dict | None = None


def _get_client_config() -> Dict:
    """Load Google Drive OAuth client configuration (cached)."""
    global _CLIENT_CONFIG
    if _CLIENT_CONFIG is not None:
        return _CLIENT_CONFIG

    # Try multiple paths for the credentials file
    project_root = Path(__file__).parent.parent.parent
    candidates = [
        project_root / "google-drive-credentials.json",
        project_root.parent / "google-drive-credentials.json",
    ]
    for p in candidates:
        if p.exists():
            with open(p, "r") as f:
                _CLIENT_CONFIG = json.load(f)
            logger.info("Loaded Google Drive credentials from %s", p)
            return _CLIENT_CONFIG

    # Fallback: build config from environment variables
    client_id = os.environ.get("GOOGLE_DRIVE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        logger.error("Google Drive credentials file not found and GOOGLE_DRIVE_CLIENT_ID/SECRET env vars not set")
        return None
    _CLIENT_CONFIG = {
        "web": {
            "client_id": client_id,
            "project_id": os.environ.get("GOOGLE_PROJECT_ID", "compliance-copilot"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
        }
    }
    logger.warning("Using Google Drive client config from environment variables")
    return _CLIENT_CONFIG


def _client_key() -> str:
    """Return the top-level key in the client config ('web' or 'installed')."""
    cfg = _get_client_config()
    if "web" in cfg:
        return "web"
    if "installed" in cfg:
        return "installed"
    raise RuntimeError("Invalid Google Drive credentials format")


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def get_auth_url(redirect_uri: str) -> Tuple[str, str]:
    """Generate OAuth 2.0 authorization URL.

    Returns:
        (auth_url, state) tuple
    """
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    logger.info("Generated Google Drive OAuth URL (state=%s)", state)
    return auth_url, state


def exchange_code_for_credentials(code: str, redirect_uri: str) -> Credentials:
    """Exchange an authorization code for OAuth credentials."""
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    logger.info("Exchanged authorization code for credentials")
    return flow.credentials


def refresh_credentials(creds_dict: Dict) -> Credentials:
    """Refresh expired OAuth credentials using the stored refresh token."""
    cfg = _get_client_config()
    key = _client_key()
    creds = Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=cfg[key]["token_uri"],
        client_id=cfg[key]["client_id"],
        client_secret=cfg[key]["client_secret"],
    )
    creds.refresh(Request())
    logger.info("Refreshed Google Drive credentials")
    return creds


def credentials_to_dict(creds: Credentials) -> Dict:
    """Serialize a Credentials object to a storable dict."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }


def dict_to_credentials(creds_dict: Dict) -> Credentials:
    """Deserialize a dict back to a Credentials object."""
    return Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri"),
        client_id=creds_dict.get("client_id"),
        client_secret=creds_dict.get("client_secret"),
        scopes=creds_dict.get("scopes"),
    )


# ---------------------------------------------------------------------------
# Token storage (Firestore)
# ---------------------------------------------------------------------------

def store_tokens(org_id: str, creds: Credentials, email: str = "") -> None:
    """Persist OAuth tokens in Firestore keyed by org_id."""
    data = credentials_to_dict(creds)
    data["email"] = email
    # Use org_id as the document ID for easy lookup
    existing = get_document(TOKEN_COLLECTION, org_id)
    if existing:
        update_document(TOKEN_COLLECTION, org_id, data)
    else:
        create_document(TOKEN_COLLECTION, data, doc_id=org_id)
    logger.info("Stored Google Drive tokens for org %s", org_id)


def load_tokens(org_id: str) -> Optional[Dict]:
    """Load stored OAuth tokens from Firestore."""
    doc = get_document(TOKEN_COLLECTION, org_id)
    if doc and doc.get("refresh_token"):
        return doc
    return None


def delete_tokens(org_id: str) -> bool:
    """Remove stored OAuth tokens from Firestore."""
    return delete_document(TOKEN_COLLECTION, org_id)


# ---------------------------------------------------------------------------
# Credential resolution with auto-refresh
# ---------------------------------------------------------------------------

def get_valid_credentials(org_id: str) -> Credentials:
    """Load credentials for an org, refreshing if expired.

    Raises:
        RuntimeError: If no stored tokens or refresh fails.
    """
    token_data = load_tokens(org_id)
    if not token_data:
        raise RuntimeError("Google Drive not connected. Please authenticate first.")

    creds = dict_to_credentials(token_data)

    # Check if token is expired or missing
    if not creds.token or (creds.expired and creds.refresh_token):
        try:
            creds = refresh_credentials(token_data)
            # Persist the refreshed tokens
            store_tokens(org_id, creds, email=token_data.get("email", ""))
            logger.info("Auto-refreshed Google Drive tokens for org %s", org_id)
        except Exception as e:
            logger.error("Token refresh failed for org %s: %s", org_id, e)
            raise RuntimeError(
                "Google Drive token expired and refresh failed. Please re-authenticate."
            ) from e

    return creds


# ---------------------------------------------------------------------------
# Drive API operations
# ---------------------------------------------------------------------------

def _build_service(creds: Credentials):
    """Build a Google Drive API v3 service."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_user_email(creds: Credentials) -> str:
    """Fetch the email of the authenticated Google user."""
    try:
        service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = service.userinfo().get().execute()
        return info.get("email", "")
    except Exception as e:
        logger.warning("Failed to get user email: %s", e)
        return ""


def list_all_folders(creds: Credentials, max_results: int = 1000) -> List[Dict]:
    """List all folders in the user's Google Drive."""
    service = _build_service(creds)
    query = "mimeType = 'application/vnd.google-apps.folder' and trashed=false"
    all_folders: List[Dict] = []
    page_token = None

    while True:
        results = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, modifiedTime, parents)",
            pageSize=100,
            orderBy="name",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        all_folders.extend(results.get("files", []))
        page_token = results.get("nextPageToken")

        if not page_token or len(all_folders) >= max_results:
            break

    logger.info("Listed %d folders", len(all_folders[:max_results]))
    return all_folders[:max_results]


def list_files_in_folder(creds: Credentials, folder_id: str, page_size: int = 100) -> List[Dict]:
    """List files in a specific Google Drive folder with validity flags."""
    service = _build_service(creds)
    query = f"'{folder_id}' in parents and trashed=false"
    files: List[Dict] = []
    page_token = None

    while True:
        results = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            pageSize=page_size,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        for f in results.get("files", []):
            size = int(f.get("size", 0))
            mime = f.get("mimeType", "")
            f["valid"] = mime in ALLOWED_MIME_TYPES and size <= MAX_FILE_SIZE
            files.append(f)

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    logger.info("Listed %d files in folder %s", len(files), folder_id)
    return files


def download_file(creds: Credentials, file_id: str, file_name: str | None = None) -> Tuple[bytes, str]:
    """Download a file from Google Drive.

    Returns:
        (file_bytes, file_name)
    """
    service = _build_service(creds)

    if not file_name:
        metadata = service.files().get(
            fileId=file_id,
            fields="name",
            supportsAllDrives=True,
        ).execute()
        file_name = metadata.get("name", f"file-{file_id}")

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    file_bytes = file_stream.getvalue()
    logger.info("Downloaded %s (%d bytes)", file_name, len(file_bytes))
    return file_bytes, file_name
