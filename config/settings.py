"""
CandidateFusion AI — Application Settings

Centralised, strongly-typed configuration loaded from environment variables
and/or a .env file.  All modules should import the singleton ``get_settings()``
rather than reading os.environ directly so that:

  1. Config is validated at startup (Pydantic will raise immediately on bad values).
  2. Tests can override settings via dependency injection.
  3. There is a single source of truth for every tunable.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class PDFExtractionStrategy(StrEnum):
    PDFPLUMBER = "pdfplumber"
    PYMUPDF = "pymupdf"


class NullHandling(StrEnum):
    OMIT = "omit"
    NULL = "null"
    EMPTY = "empty"


class Settings(BaseSettings):
    """
    Application-wide settings.

    Values are read from environment variables (case-insensitive).
    A .env file is loaded if present; explicit env vars always take precedence.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = Field(default="CandidateFusion AI", description="Application display name")
    app_env: AppEnv = Field(default=AppEnv.DEVELOPMENT, description="Runtime environment")
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Root log level")
    log_format: LogFormat = Field(default=LogFormat.JSON, description="Log output format")

    # ── GitHub API ───────────────────────────────────────────────────────────
    github_token: str | None = Field(
        default=None,
        description="GitHub PAT — optional but strongly recommended for rate limit",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="GitHub REST API base URL",
    )
    github_api_timeout_seconds: int = Field(
        default=15,
        ge=1,
        le=120,
        description="Per-request timeout for GitHub API calls",
    )
    github_api_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for transient GitHub API errors",
    )

    # ── Pipeline ─────────────────────────────────────────────────────────────
    pipeline_default_config_path: Path = Field(
        default=Path("config/default.json"),
        description="Default output projection config path",
    )
    pipeline_output_dir: Path = Field(
        default=Path("outputs"),
        description="Directory for pipeline output files",
    )
    pipeline_log_dir: Path = Field(
        default=Path("logs"),
        description="Directory for structured log files",
    )
    pipeline_max_workers: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum parallel workers for concurrent extraction",
    )

    # ── FastAPI ──────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", description="API server bind host")
    api_port: int = Field(default=8000, ge=1024, le=65535, description="API server port")
    api_workers: int = Field(default=1, ge=1, le=16, description="Uvicorn worker count")
    api_reload: bool = Field(default=True, description="Hot-reload (disable in production)")

    # ── PDF Processing ───────────────────────────────────────────────────────
    pdf_max_pages: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of pages to process from a PDF",
    )
    pdf_text_extraction_strategy: PDFExtractionStrategy = Field(
        default=PDFExtractionStrategy.PDFPLUMBER,
        description="Primary PDF text extraction library",
    )

    # ── Validation ───────────────────────────────────────────────────────────
    validation_strict_mode: bool = Field(
        default=False,
        description="When True, any validation failure aborts the pipeline",
    )

    # ── Source Confidence Weights (must sum to ≤ 1 each, not cumulative) ───
    confidence_weight_ats: float = Field(default=0.95, ge=0.0, le=1.0)
    confidence_weight_csv: float = Field(default=0.92, ge=0.0, le=1.0)
    confidence_weight_resume: float = Field(default=0.90, ge=0.0, le=1.0)
    confidence_weight_github: float = Field(default=0.80, ge=0.0, le=1.0)
    confidence_weight_notes: float = Field(default=0.70, ge=0.0, le=1.0)

    @field_validator("pipeline_output_dir", "pipeline_log_dir", mode="before")
    @classmethod
    def _ensure_path(cls, v: str | Path) -> Path:
        return Path(v)

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    @property
    def source_weights(self) -> dict[str, float]:
        return {
            "ats": self.confidence_weight_ats,
            "csv": self.confidence_weight_csv,
            "resume": self.confidence_weight_resume,
            "github": self.confidence_weight_github,
            "notes": self.confidence_weight_notes,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    The cache ensures that environment variables are parsed exactly once.
    In tests, call ``get_settings.cache_clear()`` after patching env vars.
    """
    return Settings()
