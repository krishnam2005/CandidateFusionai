"""
models.metadata — Pipeline execution metadata and source type enumeration.

SourceType is the authoritative enum used by every module to identify which
upstream source a piece of data originated from.  PipelineMetadata captures
end-to-end timing and provenance at the run level.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    """Canonical identifiers for every supported input source."""

    ATS = "ats"
    CSV = "csv"
    RESUME = "resume"
    GITHUB = "github"
    NOTES = "notes"
    UNKNOWN = "unknown"


class SourceMeta(BaseModel):
    """Metadata captured for each source that participated in a pipeline run."""

    source: SourceType
    raw_path: str | None = None
    """Filesystem path or URL of the original input."""
    extraction_started_at: datetime | None = None
    extraction_completed_at: datetime | None = None
    extraction_duration_ms: float | None = None
    record_count: int = 0
    """Number of top-level records extracted (1 for single-candidate sources)."""
    error: str | None = None
    """Non-None if extraction failed; pipeline continues with partial data."""

    @property
    def succeeded(self) -> bool:
        return self.error is None


class PipelineMetadata(BaseModel):
    """
    Top-level execution metadata attached to every output profile.

    Captures timing, source participation, and version info so that
    downstream consumers can audit exactly how a profile was produced.
    """

    run_id: UUID = Field(default_factory=uuid4, description="Unique pipeline run identifier")
    pipeline_version: str = Field(
        default="1.0.0",
        description="CandidateFusion pipeline semantic version",
    )
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the pipeline run began",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the pipeline run finished",
    )
    duration_ms: float | None = Field(
        default=None,
        description="Total wall-clock time in milliseconds",
    )
    sources_requested: list[SourceType] = Field(
        default_factory=list,
        description="Sources provided by the caller",
    )
    sources_succeeded: list[SourceType] = Field(
        default_factory=list,
        description="Sources that extracted successfully",
    )
    sources_failed: list[SourceType] = Field(
        default_factory=list,
        description="Sources that encountered errors during extraction",
    )
    source_details: list[SourceMeta] = Field(
        default_factory=list,
        description="Per-source timing and error information",
    )
    output_config_path: str | None = Field(
        default=None,
        description="Path to the projection config used for this run",
    )
    validation_passed: bool = Field(
        default=True,
        description="False if any validation rule produced an ERROR-level finding",
    )
    validation_warnings: int = Field(
        default=0,
        description="Number of validation warnings (non-blocking)",
    )
    validation_errors: int = Field(
        default=0,
        description="Number of validation errors",
    )

    # ── Source priority order (highest → lowest) ──────────────────────────
    SOURCE_PRIORITY: list[SourceType] = [
        SourceType.ATS,
        SourceType.CSV,
        SourceType.RESUME,
        SourceType.GITHUB,
        SourceType.NOTES,
    ]

    model_config = {"arbitrary_types_allowed": True}

    Annotated[list[SourceType], Field(description="Priority-ordered sources")]

    def mark_completed(self, duration_ms: float) -> None:
        """Set completion timestamp and duration in-place."""
        self.completed_at = datetime.utcnow()
        self.duration_ms = duration_ms
