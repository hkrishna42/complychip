"""ComplyChip V3 - Global Exception Handlers

Registers application-wide exception handlers so that every error response
is a consistent JSON payload rather than an HTML trace or plain text.
"""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import DEBUG

logger = logging.getLogger("complychip.errors")


def setup_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI application.

    Three handlers are installed:

    1. **HTTPException** -- returns ``{"error": detail, "status_code": code}``.
    2. **RequestValidationError** -- returns a 422 with structured field errors.
    3. **Exception** (catch-all) -- returns a generic 500.  When ``DEBUG`` is
       enabled, the actual error message is included in the response body.

    Parameters
    ----------
    app:
        The FastAPI application instance.
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        formatted_errors = []
        for err in exc.errors():
            loc = " -> ".join(str(part) for part in err.get("loc", []))
            formatted_errors.append(
                {
                    "field": loc,
                    "message": err.get("msg", "Invalid value"),
                    "type": err.get("type", "value_error"),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation error",
                "details": formatted_errors,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )

        content: dict = {"error": "Internal server error"}
        if DEBUG:
            content["debug_message"] = str(exc)
            content["traceback"] = traceback.format_exception_only(type(exc), exc)

        return JSONResponse(status_code=500, content=content)
