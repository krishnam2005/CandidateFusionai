"""
models.confidence — Per-field and aggregate confidence scoring models.

Confidence is distinct from provenance:
  - Provenance says *where* a value came from.
  - Confidence says *how trustworthy* that value is.

The ConfidenceEngine computes these from:
  1. Source base weight (ATS=0.95, CSV=0.92, …)
  2. Cross-source agreement bonus (+0.05 per agreeing source)
  3. Cross-source disagreement penalty (−0.10 per disagreeing source)
  4. Field-specific modifiers (e.g., email validated → +0.05)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FieldConfidence(BaseModel):
    """
    Confidence score for a single canonical field.

    Attributes
    ----------
    field_name:
        Dotted path to the canonical field (e.g. ``"full_name"``, ``"emails"``).
    score:
        Final confidence in [0, 1].  Values ≥ 0.90 are considered high-confidence.
    base_score:
        Source weight before agreement/disagreement adjustments.
    agreement_bonus:
        Cumulative bonus from multiple sources providing the same value.
    disagreement_penalty:
        Cumulative penalty from conflicting source values.
    sources_agreed:
        Number of sources that provided identical (post-normalization) values.
    sources_disagreed:
        Number of sources that provided conflicting values.
    explanation:
        Human-readable breakdown of how the score was computed.
    """

    field_name: str
    score: float = Field(ge=0.0, le=1.0)
    base_score: float = Field(ge=0.0, le=1.0)
    agreement_bonus: float = Field(default=0.0, ge=0.0)
    disagreement_penalty: float = Field(default=0.0, ge=0.0)
    sources_agreed: int = Field(default=0, ge=0)
    sources_disagreed: int = Field(default=0, ge=0)
    explanation: str = ""


class ConfidenceRecord(BaseModel):
    """
    Aggregate confidence summary attached to the final canonical profile.

    ``overall_score`` is the mean of all per-field confidence scores,
    weighted by field importance (defined in the ConfidenceEngine).
    ``fields`` maps field name → FieldConfidence for full transparency.
    """

    overall_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean confidence across all scored fields",
    )
    fields: dict[str, FieldConfidence] = Field(
        default_factory=dict,
        description="Per-field confidence breakdown",
    )
    high_confidence_fields: list[str] = Field(
        default_factory=list,
        description="Fields with confidence ≥ 0.90",
    )
    low_confidence_fields: list[str] = Field(
        default_factory=list,
        description="Fields with confidence < 0.70",
    )
    sources_used: list[str] = Field(
        default_factory=list,
        description="Source identifiers that contributed to this profile",
    )
