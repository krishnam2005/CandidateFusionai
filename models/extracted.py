"""
models.extracted — Intermediate representation produced by each extractor.

ExtractedCandidate is intentionally lenient (all fields optional, extra
fields ignored) because raw sources are messy.  It is distinct from the
canonical Candidate to preserve the separation between:
  - Extraction: raw → ExtractedCandidate  (per-source)
  - Mapping:    ExtractedCandidate → Candidate  (canonical mapper)
  - Merge:      [Candidate] → Candidate  (merge engine)

Using a separate intermediate type rather than directly emitting Candidate
from extractors means:
  1. Extractors don't need to know about provenance or confidence.
  2. The canonical mapper can apply normalization before merging.
  3. Schema evolution in Candidate doesn't break extractors.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from models.metadata import SourceType


class RawExperience(BaseModel):
    company: str | None = None
    title: str | None = None
    location_raw: str | None = None
    start_date_raw: str | None = None
    end_date_raw: str | None = None
    is_current: bool = False
    description: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class RawEducation(BaseModel):
    institution: str | None = None
    degree_raw: str | None = None
    field_of_study: str | None = None
    start_date_raw: str | None = None
    end_date_raw: str | None = None
    gpa_raw: str | None = None
    honors: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class RawProject(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str | None = None
    repository_url: str | None = None
    technologies: list[str] = Field(default_factory=list)
    start_date_raw: str | None = None
    end_date_raw: str | None = None
    is_open_source: bool = False
    stars: int | None = None
    forks: int | None = None

    model_config = {"extra": "ignore"}


class RawCertification(BaseModel):
    name: str | None = None
    issuing_organization: str | None = None
    issue_date_raw: str | None = None
    expiry_date_raw: str | None = None
    credential_id: str | None = None
    credential_url: str | None = None

    model_config = {"extra": "ignore"}


class ExtractedCandidate(BaseModel):
    """
    Loosely-typed intermediate extraction result.

    Accepts whatever a given source provides without enforcing strict
    schemas.  The canonical mapper is responsible for validation and
    type coercion.
    """

    source: SourceType = Field(description="Which extractor produced this record")
    raw_path: str | None = Field(
        default=None,
        description="Filesystem path or URL of the source input",
    )

    # ── Identity ──────────────────────────────────────────────────────────
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    preferred_name: str | None = None

    # ── Contact ───────────────────────────────────────────────────────────
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location_raw: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None

    # ── Professional ─────────────────────────────────────────────────────
    summary: str | None = None
    headline: str | None = None
    years_of_experience: float | None = None

    # ── Collections ───────────────────────────────────────────────────────
    skills_raw: list[str] = Field(default_factory=list)
    experience: list[RawExperience] = Field(default_factory=list)
    education: list[RawEducation] = Field(default_factory=list)
    projects: list[RawProject] = Field(default_factory=list)
    certifications: list[RawCertification] = Field(default_factory=list)
    social_links: list[dict[str, Any]] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    # ── Source-specific extras ────────────────────────────────────────────
    github_username: str | None = None
    github_repos_count: int | None = None
    github_followers: int | None = None
    github_following: int | None = None
    github_public_gists: int | None = None
    ats_candidate_id: str | None = None
    ats_status: str | None = None

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}
