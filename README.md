# ComplyChip

AI-powered Compliance Management Platform with real-time document analysis, risk scoring, and regulatory monitoring.

## Features

- **Document Management** — Upload, analyze, and track compliance documents with AI-powered extraction
- **Entity/Vendor Monitoring** — Track compliance scores across entities with risk-level assessments
- **AI Analysis Pipeline** — n8n workflow with Gemini AI for document analysis, key clause extraction, and risk flagging
- **Gap Analysis** — Automated compliance gap detection with severity ratings and recommendations
- **Google Drive Integration** — Import documents directly from Google Drive
- **Copilot** — AI-powered compliance assistant for natural language queries
- **Knowledge Graph** — Visual relationship mapping between entities, documents, and regulations
- **Analytics Dashboard** — Compliance trends, risk matrices, and expiry forecasting
- **Pinecone Vector Search** — Semantic document search via embeddings

## Tech Stack

- **Backend**: Python / FastAPI
- **Frontend**: Vanilla HTML/CSS/JS with Chart.js
- **Database**: Firebase Firestore
- **AI Pipeline**: n8n + Google Gemini
- **Vector DB**: Pinecone
- **Storage**: Google Cloud Storage

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your credentials

# Run the server
python3 -m backend.server
```

Server runs at `http://localhost:8000`

## Project Structure

```
complychip/
├── backend/
│   ├── server.py              # FastAPI application
│   ├── config.py              # Configuration
│   ├── routes/
│   │   ├── auth.py            # Authentication & JWT
│   │   ├── documents.py       # Document CRUD & analysis
│   │   ├── upload.py          # Upload pipeline (n8n + AI)
│   │   ├── google_drive.py    # Google Drive integration
│   │   ├── compliance.py      # Compliance rules & gaps
│   │   ├── copilot.py         # AI assistant
│   │   ├── graph.py           # Knowledge graph
│   │   └── vendors.py         # Vendor management
│   ├── services/
│   │   ├── firebase_service.py
│   │   ├── gemini_service.py
│   │   ├── n8n_client.py
│   │   ├── pinecone_service.py
│   │   └── google_drive_service.py
│   └── middleware/
│       ├── rate_limiter.py
│       ├── audit_logger.py
│       └── error_handler.py
├── frontend/
│   ├── dashboard.html
│   ├── documents.html
│   ├── entities.html
│   ├── upload.html
│   ├── analytics.html
│   ├── copilot.html
│   ├── settings.html
│   ├── css/design-system.css
│   └── js/
│       ├── api.js
│       ├── components.js
│       └── charts.js
└── n8n-workflows/             # n8n workflow definitions
```

## License

MIT
