"""ComplyChip V3 - FastAPI Application Server"""
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.config import HOST, PORT, DEBUG
from backend.middleware.rate_limiter import setup_rate_limiter
from backend.middleware.error_handler import setup_error_handlers
from backend.middleware.audit_logger import AuditLogMiddleware


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Add no-cache headers to JS/CSS files during development."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/js/") or path.startswith("/css/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ComplyChip V3 - AI-Powered Compliance Intelligence",
        description="Enterprise compliance document management and analysis platform",
        version="3.0.0",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Audit logging middleware (before other middleware so it captures all requests)
    app.add_middleware(AuditLogMiddleware)

    # No-cache middleware for dev
    if DEBUG:
        app.add_middleware(NoCacheStaticMiddleware)

    # Rate limiting
    setup_rate_limiter(app)

    # Global error handlers
    setup_error_handlers(app)

    # Register route modules (import lazily to avoid circular deps)
    _register_routes(app)

    # Serve frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
        if (FRONTEND_DIR / "assets").exists():
            app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    # HTML page routes
    @app.get("/")
    async def serve_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{page}.html")
    async def serve_page(page: str):
        file_path = FRONTEND_DIR / f"{page}.html"
        if file_path.exists():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    return app


def _register_routes(app: FastAPI):
    """Register all API route modules."""
    try:
        from backend.routes.auth import router as auth_router
        app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
    except ImportError:
        pass

    try:
        from backend.routes.documents import router as documents_router
        app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
    except ImportError:
        pass

    try:
        from backend.routes.entities import router as entities_router
        app.include_router(entities_router, prefix="/api/entities", tags=["Entities"])
    except ImportError:
        pass

    try:
        from backend.routes.upload import router as upload_router
        app.include_router(upload_router, prefix="/api/upload", tags=["Upload"])
    except ImportError:
        pass

    try:
        from backend.routes.analytics import router as analytics_router
        app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])
    except ImportError:
        pass

    try:
        from backend.routes.copilot import router as copilot_router
        app.include_router(copilot_router, prefix="/api/copilot", tags=["Copilot"])
    except ImportError:
        pass

    try:
        from backend.routes.compliance import router as compliance_router
        app.include_router(compliance_router, prefix="/api/compliance", tags=["Compliance"])
    except ImportError:
        pass

    try:
        from backend.routes.vendors import router as vendors_router
        app.include_router(vendors_router, prefix="/api/vendors", tags=["Vendors"])
    except ImportError:
        pass

    try:
        from backend.routes.graph import router as graph_router
        app.include_router(graph_router, prefix="/api/graph", tags=["Knowledge Graph"])
    except ImportError:
        pass

    try:
        from backend.routes.regulatory import router as regulatory_router
        app.include_router(regulatory_router, prefix="/api/regulatory", tags=["Regulatory"])
    except ImportError:
        pass

    try:
        from backend.routes.admin import router as admin_router
        app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
    except ImportError:
        pass

    try:
        from backend.routes.webhooks import router as webhooks_router
        app.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])
    except ImportError:
        pass

    try:
        from backend.routes.google_drive import router as google_drive_router
        app.include_router(google_drive_router, prefix="/google-drive", tags=["Google Drive"])
    except ImportError:
        pass


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "backend.server:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
    )
