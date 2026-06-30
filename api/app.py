"""
api.app — FastAPI application factory for CandidateFusion AI.

Architecture note:
  We use an application factory (``create_app()``) rather than a module-level
  ``app`` instance.  This enables:
    - Per-test application creation with different settings (testability).
    - Multiple app instances in the same process if needed.
    - Deferred startup (useful in serverless environments).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import transform_router
from config.settings import get_settings
from utils.logging import get_logger, setup_logging


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager.

    Runs setup on startup and teardown on shutdown.
    """
    settings = get_settings()
    setup_logging(
        log_level=settings.log_level.value,
        log_format=settings.log_format.value,
        log_dir=settings.pipeline_log_dir,
    )
    log = get_logger(__name__)
    log.info("api_startup", app_name=settings.app_name, env=settings.app_env.value)
    yield
    log.info("api_shutdown")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns
    -------
    FastAPI
        The fully configured application instance.
    """
    settings = get_settings()

    application = FastAPI(
        title="CandidateFusion AI",
        description=(
            "Multi-Source Candidate Data Transformer.\n\n"
            "Ingests candidate information from CSV, ATS JSON, PDF resumes, "
            "GitHub profiles, and recruiter notes, then produces a unified "
            "canonical candidate profile with provenance and confidence scoring."
        ),
        version="1.0.0",
        contact={
            "name": "Eightfold AI Engineering",
            "email": "engineering@eightfold.ai",
        },
        license_info={"name": "MIT"},
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────
    application.include_router(transform_router, prefix="/api/v1")

    # ── Health check ──────────────────────────────────────────────────────
    @application.get("/health", tags=["System"])
    async def health_check() -> dict[str, str]:
        """System health check endpoint."""
        return {"status": "healthy", "version": "1.0.0"}

    # ── UI (serve ui/index.html at /) ─────────────────────────────────────
    _ui_dir = Path(__file__).parent.parent / "ui"
    if _ui_dir.exists():
        application.mount("/ui", StaticFiles(directory=str(_ui_dir)), name="ui")

        @application.get("/", include_in_schema=False)
        async def serve_ui() -> FileResponse:
            """Redirect root to the UI."""
            return FileResponse(str(_ui_dir / "index.html"))

    return application


# Module-level app instance for uvicorn
app = create_app()
