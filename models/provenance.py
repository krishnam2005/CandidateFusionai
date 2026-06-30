"""
models.provenance — Field-level provenance tracking.

Every scalar field in the canonical Candidate model can optionally carry a
ProvenanceRecord that answers the questions:
  - Where did this value come from?
  - How was it extracted?
  - When was it extracted?
  - How confident are we in this value?

This design supports full auditability without coupling the provenance data
structure to any particular field shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from models.metadata import SourceType


class ExtractionMethod(str):
    """
    Represents the extraction technique used to obtain a field value.

    Using str subclass (not StrEnum) so callers can pass arbitrary method
    descriptions without being forced to update the enum.
    """


# ── Well-known extraction method constants ────────────────────────────────────
DIRECT_FIELD = "direct_field_mapping"
REGEX_PATTERN = "regex_pattern"
NLP_ENTITY = "nlp_entity_extraction"
GITHUB_API = "github_rest_api"
PDF_TEXT = "pdf_text_extraction"
CSV_COLUMN = "csv_column_mapping"
JSON_PATH = "json_path_mapping"
FUZZY_MATCH = "fuzzy_string_match"
INFERRED = "inferred_from_context"


class ProvenanceRecord(BaseModel):
    """
    Captures the full lineage of a single field value.

    Design notes:
    - ``value`` is typed as ``Any`` because provenance applies to both
      scalar fields (str, int) and complex ones (lists, dicts).
    - ``confidence`` is the per-extraction confidence, before any
      cross-source agreement adjustment by the ConfidenceEngine.
    - ``raw_value`` preserves the pre-normalization value for debugging.
    """

    source: SourceType = Field(description="Which input source produced this value")
    extraction_method: str = Field(description="Technique used to extract the value")
    value: Any = Field(description="Normalized value as stored in the canonical profile")
    raw_value: Any = Field(
        default=None,
        description="Pre-normalization value (diagnostic aid)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction-time confidence [0, 1]",
    )
    extracted_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of extraction",
    )
    notes: str | None = Field(
        default=None,
        description="Human-readable notes on how this value was derived",
    )

    model_config = {"arbitrary_types_allowed": True}


class FieldProvenance(BaseModel):
    """
    Container for the full provenance history of a single canonical field.

    When multiple sources provide a value for the same field, the merge
    engine selects a winner and stores all candidates here for audit.
    """

    field_name: str = Field(description="Dotted path to the canonical field (e.g. 'emails[0]')")
    selected: ProvenanceRecord = Field(description="The provenance record of the winning value")
    candidates: list[ProvenanceRecord] = Field(
        default_factory=list,
        description="All provenance records considered during merge",
    )
    conflict_resolved: bool = Field(
        default=False,
        description="True if multiple sources disagreed and resolution was required",
    )
    resolution_reason: str | None = Field(
        default=None,
        description="Human-readable explanation of which merge rule applied",
    )

    model_config = {"arbitrary_types_allowed": True}
