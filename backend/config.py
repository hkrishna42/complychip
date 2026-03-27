"""ComplyChip V3 - Central Configuration"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# JWT Authentication
JWT_SECRET = os.getenv("JWT_SECRET", "complychip-dev-secret-change-in-prod")
JWT_REFRESH_SECRET = os.getenv("JWT_REFRESH_SECRET", "complychip-refresh-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Encryption
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# Google Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Pinecone Vector Database
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "complychip-docs")

# n8n Workflow Orchestration
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "https://hkrishna42.app.n8n.cloud")
N8N_DOCUMENT_INTAKE_WEBHOOK = f"{N8N_BASE_URL}/webhook/document-intake"
N8N_COMPLIANCE_EVAL_WEBHOOK = f"{N8N_BASE_URL}/webhook/compliance-evaluation"
N8N_SEND_REMINDER_WEBHOOK = f"{N8N_BASE_URL}/webhook/send-reminder"
N8N_VENDOR_ENRICHMENT_WEBHOOK = f"{N8N_BASE_URL}/webhook/vendor-enrichment"
N8N_RISK_ANALYSIS_WEBHOOK = f"{N8N_BASE_URL}/webhook/risk-analysis"
N8N_CLAUSE_ANOMALY_WEBHOOK = f"{N8N_BASE_URL}/webhook/clause-anomaly"
N8N_COPILOT_AGENT_WEBHOOK = f"{N8N_BASE_URL}/webhook/copilot-agent"
N8N_REPLACE_DOCUMENT_WEBHOOK = f"{N8N_BASE_URL}/webhook/replace-document"

# Firebase / Firestore
FIREBASE_CRED_PATH = os.getenv(
    "FIREBASE_CRED_PATH",
    "compliance-copilot-1b982-firebase-adminsdk-fbsvc-694228dbe2.json"
)

# Google Cloud Storage
GCS_BUCKET = os.getenv("GCS_BUCKET", "compliance-test-v1")

# Google Drive OAuth
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID", "")
GOOGLE_DRIVE_CLIENT_SECRET = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", "")

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# --- Lazy-initialized clients ---

_firebase_app = None
_firestore_client = None
_gcs_client = None


def get_firebase_app():
    """Initialize Firebase app (lazy singleton)."""
    global _firebase_app
    if _firebase_app is None:
        try:
            import firebase_admin
            from firebase_admin import credentials
            # Check multiple possible paths for the credential file
            cred_path = FIREBASE_CRED_PATH
            if not os.path.isabs(cred_path):
                # Try project root first
                root_path = PROJECT_ROOT / cred_path
                if root_path.exists():
                    cred_path = str(root_path)
                else:
                    # Try parent directory (main repo)
                    parent_path = PROJECT_ROOT.parent / cred_path
                    if parent_path.exists():
                        cred_path = str(parent_path)
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_path)
                _firebase_app = firebase_admin.initialize_app(cred)
            else:
                _firebase_app = firebase_admin.get_app()
        except Exception as e:
            print(f"Warning: Firebase initialization failed: {e}")
            print("Running in demo mode without Firebase.")
    return _firebase_app


def get_firestore_client():
    """Get Firestore client (lazy singleton)."""
    global _firestore_client
    if _firestore_client is None:
        try:
            get_firebase_app()
            from firebase_admin import firestore
            _firestore_client = firestore.client()
        except Exception as e:
            print(f"Warning: Firestore client failed: {e}")
    return _firestore_client


def get_gcs_client():
    """Get Google Cloud Storage client (lazy singleton)."""
    global _gcs_client
    if _gcs_client is None:
        try:
            from google.cloud import storage as gcs_storage
            from google.oauth2 import service_account
            cred_path = FIREBASE_CRED_PATH
            if not os.path.isabs(cred_path):
                root_path = PROJECT_ROOT / cred_path
                if root_path.exists():
                    cred_path = str(root_path)
                else:
                    parent_path = PROJECT_ROOT.parent / cred_path
                    if parent_path.exists():
                        cred_path = str(parent_path)
            gcs_credentials = service_account.Credentials.from_service_account_file(cred_path)
            _gcs_client = gcs_storage.Client(
                credentials=gcs_credentials,
                project=gcs_credentials.project_id,
            )
        except Exception as e:
            print(f"Warning: GCS client failed: {e}")
    return _gcs_client
