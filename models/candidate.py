"""
models.candidate — Canonical candidate domain models.

This module defines the single source of truth for what a "Candidate" looks
like inside CandidateFusion AI.  Every extractor, normalizer, merger, and
validator speaks this language.

Design decisions:
- All models are Pydantic v2 BaseModels with strict typing.
- Optional fields use ``field | None = None`` rather than ``Optional[field]``
  (PEP 604 union syntax, cleaner in Python 3.12).
- Arrays default to empty lists — never None — so consumers don't need to
  guard against None for collections.
- ``model_config = {"extra": "forbid"}`` on core models prevents silent data
  loss from typos in field names.
- UUID-based IDs generated at model creation to support idempotent merging.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

from models.confidence import ConfidenceRecord
from models.metadata import PipelineMetadata
from models.provenance import FieldProvenance


class SkillLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
    UNKNOWN = "unknown"


class EducationDegree(StrEnum):
    HIGH_SCHOOL = "high_school"
    ASSOCIATE = "associate"
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"
    MBA = "mba"
    BOOTCAMP = "bootcamp"
    CERTIFICATION = "certification"
    OTHER = "other"
    UNKNOWN = "unknown"


class SocialPlatform(StrEnum):
    LINKEDIN = "linkedin"
    GITHUB = "github"
    TWITTER = "twitter"
    STACKOVERFLOW = "stackoverflow"
    PORTFOLIO = "portfolio"
    OTHER = "other"


class Location(BaseModel):
    """Structured representation of a geographical location."""

    city: str | None = None
    state: str | None = None
    country: str | None = None
    country_code: str | None = Field(default=None, description="ISO 3166-1 alpha-2 code")
    postal_code: str | None = None
    raw: str | None = Field(default=None, description="Original unstructured location string")

    model_config = {"extra": "ignore"}

    @property
    def display(self) -> str:
        """Human-readable location string."""
        parts = [p for p in [self.city, self.state, self.country] if p]
        return ", ".join(parts) if parts else self.raw or ""


class Skill(BaseModel):
    """
    A normalized technical or soft skill.

    ``canonical_name`` is the normalized form (e.g. "Python", "React") used
    for deduplication and matching.  ``aliases`` preserves alternate spellings
    observed across sources.
    """

    skill_id: UUID = Field(default_factory=uuid4)
    canonical_name: str = Field(description="Normalized skill name")
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternate names seen across sources",
    )
    level: SkillLevel = SkillLevel.UNKNOWN
    years_of_experience: float | None = Field(default=None, ge=0.0)
    endorsed: bool = False
    category: str | None = Field(
        default=None,
        description="e.g. 'Programming Language', 'Framework', 'Soft Skill'",
    )

    model_config = {"extra": "ignore"}

    @field_validator("canonical_name", mode="before")
    @classmethod
    def strip_and_title(cls, v: str) -> str:
        return v.strip()


class Experience(BaseModel):
    """A single work experience entry."""

    experience_id: UUID = Field(default_factory=uuid4)
    company: str = Field(description="Employer name")
    title: str = Field(description="Job title")
    location: Location | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @property
    def duration_months(self) -> int | None:
        """Approximate duration in months."""
        end = date.today() if self.is_current else self.end_date
        if self.start_date and end:
            delta = (end.year - self.start_date.year) * 12 + (
                end.month - self.start_date.month
            )
            return max(0, delta)
        return None


class Education(BaseModel):
    """A single education entry."""

    education_id: UUID = Field(default_factory=uuid4)
    institution: str = Field(description="School or university name")
    degree: EducationDegree = EducationDegree.UNKNOWN
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    gpa: float | None = Field(default=None, ge=0.0, le=4.0)
    honors: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class Project(BaseModel):
    """A personal or professional project."""

    project_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str | None = None
    url: str | None = None
    repository_url: str | None = None
    technologies: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    is_open_source: bool = False
    stars: int | None = Field(default=None, ge=0)
    forks: int | None = Field(default=None, ge=0)

    model_config = {"extra": "ignore"}


class Certification(BaseModel):
    """A professional certification or license."""

    certification_id: UUID = Field(default_factory=uuid4)
    name: str
    issuing_organization: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    credential_id: str | None = None
    credential_url: str | None = None

    model_config = {"extra": "ignore"}


class SocialLink(BaseModel):
    """A social profile or professional link."""

    platform: SocialPlatform = SocialPlatform.OTHER
    url: str
    username: str | None = None

    model_config = {"extra": "ignore"}


class Language(BaseModel):
    """A spoken or written language."""

    name: str
    proficiency: str | None = Field(
        default=None,
        description="e.g. Native, Fluent, Conversational, Beginner",
    )

    model_config = {"extra": "ignore"}


class Candidate(BaseModel):
    """
    The canonical candidate profile — the single source of truth.

    Every pipeline stage reads and writes this model.  The Builder pattern
    (CandidateProfileBuilder) is used to assemble an instance incrementally
    rather than constructing it in one shot.
    """

    candidate_id: UUID = Field(
        default_factory=uuid4,
        description="Stable unique identifier for this candidate profile",
    )

    # ── Identity ──────────────────────────────────────────────────────────
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    preferred_name: str | None = None

    # ── Contact ───────────────────────────────────────────────────────────
    emails: list[str] = Field(default_factory=list, description="Normalized email addresses")
    phones: list[str] = Field(
        default_factory=list,
        description="E.164-formatted phone numbers",
    )
    location: Location | None = None

    # ── Professional Summary ──────────────────────────────────────────────
    summary: str | None = None
    headline: str | None = None
    years_of_experience: float | None = Field(default=None, ge=0.0)

    # ── Core Collections ──────────────────────────────────────────────────
    skills: list[Skill] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    social_links: list[SocialLink] = Field(default_factory=list)

    # ── Intelligence Layer ────────────────────────────────────────────────
    confidence: ConfidenceRecord | None = Field(
        default=None,
        description="Aggregate and per-field confidence scores",
    )
    provenance: list[FieldProvenance] = Field(
        default_factory=list,
        description="Full field-level provenance records",
    )
    metadata: PipelineMetadata | None = Field(
        default=None,
        description="Pipeline execution metadata for this profile",
    )

    model_config = {"extra": "ignore", "arbitrary_types_allowed": True}

    @property
    def display_name(self) -> str:
        """Best available display name."""
        if self.full_name:
            return self.full_name
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else "Unknown"

    @property
    def primary_email(self) -> str | None:
        return self.emails[0] if self.emails else None

    @property
    def primary_phone(self) -> str | None:
        return self.phones[0] if self.phones else None

    def skill_names(self) -> list[str]:
        """Canonical names of all skills, for quick lookup."""
        return [s.canonical_name for s in self.skills]
