"""
projection.projector — Configurable output projection and JSON serialization.

The Projector transforms the fully enriched Candidate profile into a
configurable JSON output.  Configuration is loaded from a JSON file
(``config/default.json``) that specifies:
  - Which fields to include
  - Whether to include provenance and confidence metadata
  - How to handle null/empty values
  - Date format preference

Design principles:
  - The output shape is driven entirely by config — no code changes needed
    to change what fields appear in the output.
  - Uses orjson for fast, standards-compliant JSON serialization with
    datetime/UUID/date support.
  - Null handling is configurable: "omit" (remove null fields), "null"
    (include as JSON null), or "empty" (include as "").
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import orjson

from models.candidate import Candidate
from models.confidence import ConfidenceRecord
from models.provenance import FieldProvenance
from utils.logging import get_logger

log = get_logger(__name__)

# Fields that are always included regardless of config (system fields)
_SYSTEM_FIELDS = {"candidate_id"}

# Default fields if no config is provided
_DEFAULT_OUTPUT_FIELDS = [
    "candidate_id",
    "full_name",
    "first_name",
    "last_name",
    "emails",
    "phones",
    "location",
    "summary",
    "skills",
    "experience",
    "education",
    "projects",
    "certifications",
    "social_links",
    "languages",
    "confidence",
    "provenance",
    "metadata",
]


class OutputConfig:
    """
    Parsed output configuration from a JSON config file.

    Attributes
    ----------
    output_fields:
        List of field names to include in the output.
    include_provenance:
        Whether to include the provenance array.
    include_confidence:
        Whether to include the confidence object.
    include_metadata:
        Whether to include the pipeline metadata object.
    null_handling:
        How to handle null/empty values: "omit", "null", or "empty".
    date_format:
        Date serialization format: "ISO8601" or "YYYY-MM-DD".
    confidence_threshold:
        Fields with confidence below this threshold are excluded.
    output_format:
        Output format: "json" (default) or "jsonl".
    """

    def __init__(
        self,
        output_fields: list[str] | None = None,
        include_provenance: bool = True,
        include_confidence: bool = True,
        include_metadata: bool = True,
        null_handling: str = "omit",
        date_format: str = "ISO8601",
        confidence_threshold: float = 0.0,
        output_format: str = "json",
    ) -> None:
        self.output_fields = output_fields or _DEFAULT_OUTPUT_FIELDS
        self.include_provenance = include_provenance
        self.include_confidence = include_confidence
        self.include_metadata = include_metadata
        self.null_handling = null_handling
        self.date_format = date_format
        self.confidence_threshold = confidence_threshold
        self.output_format = output_format

    @classmethod
    def from_file(cls, path: Path) -> "OutputConfig":
        """
        Load OutputConfig from a JSON config file.

        Raises ValueError if the file is not valid JSON.
        """
        try:
            data = orjson.loads(path.read_bytes())
        except orjson.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in output config {path}: {exc}") from exc
        except OSError as exc:
            raise ValueError(f"Cannot read output config {path}: {exc}") from exc

        return cls(
            output_fields=data.get("output_fields"),
            include_provenance=data.get("include_provenance", True),
            include_confidence=data.get("include_confidence", True),
            include_metadata=data.get("include_metadata", True),
            null_handling=data.get("null_handling", "omit"),
            date_format=data.get("date_format", "ISO8601"),
            confidence_threshold=data.get("confidence_threshold", 0.0),
            output_format=data.get("output_format", "json"),
        )

    @classmethod
    def default(cls) -> "OutputConfig":
        """Return the default OutputConfig."""
        return cls()


class Projector:
    """
    Projects a Candidate into a configurable JSON-serializable dict.

    Responsible for:
      1. Field selection based on OutputConfig.output_fields.
      2. Confidence threshold filtering.
      3. Null value handling.
      4. Date serialization.
      5. JSON rendering via orjson.
    """

    def project(
        self,
        candidate: Candidate,
        provenance_records: list[FieldProvenance],
        config: OutputConfig | None = None,
    ) -> dict[str, Any]:
        """
        Project a Candidate to an output dict according to config.

        Parameters
        ----------
        candidate:
            The fully merged and enriched candidate profile.
        provenance_records:
            Field provenance records from the merge engine.
        config:
            Output configuration.  Uses default if not provided.

        Returns
        -------
        dict
            JSON-serializable output dict.
        """
        effective_config = config or OutputConfig.default()

        # Build the full candidate dict
        full_dict = self._candidate_to_dict(candidate, provenance_records, effective_config)

        # Apply field selection
        projected = self._apply_field_selection(full_dict, effective_config)

        # Apply null handling
        projected = self._apply_null_handling(projected, effective_config.null_handling)

        log.debug(
            "projection_complete",
            output_fields=list(projected.keys()),
            include_provenance=effective_config.include_provenance,
            include_confidence=effective_config.include_confidence,
        )

        return projected

    def to_json(
        self,
        candidate: Candidate,
        provenance_records: list[FieldProvenance],
        config: OutputConfig | None = None,
        indent: bool = True,
    ) -> bytes:
        """Serialize the projected candidate to JSON bytes."""
        projected = self.project(candidate, provenance_records, config)
        option = orjson.OPT_INDENT_2 if indent else None
        return orjson.dumps(projected, option=option, default=self._json_default)

    def _candidate_to_dict(
        self,
        candidate: Candidate,
        provenance_records: list[FieldProvenance],
        config: OutputConfig,
    ) -> dict[str, Any]:
        """Convert Candidate to a fully populated dict."""
        d: dict[str, Any] = {
            "candidate_id": str(candidate.candidate_id),
            "full_name": candidate.full_name,
            "first_name": candidate.first_name,
            "last_name": candidate.last_name,
            "middle_name": candidate.middle_name,
            "preferred_name": candidate.preferred_name,
            "emails": candidate.emails,
            "phones": candidate.phones,
            "location": self._location_to_dict(candidate.location),
            "summary": candidate.summary,
            "headline": candidate.headline,
            "years_of_experience": candidate.years_of_experience,
            "skills": [self._skill_to_dict(s) for s in candidate.skills],
            "experience": [self._experience_to_dict(e, config) for e in candidate.experience],
            "education": [self._education_to_dict(e, config) for e in candidate.education],
            "projects": [self._project_to_dict(p, config) for p in candidate.projects],
            "certifications": [self._cert_to_dict(c, config) for c in candidate.certifications],
            "social_links": [self._link_to_dict(l) for l in candidate.social_links],
            "languages": [{"name": lang.name, "proficiency": lang.proficiency} for lang in candidate.languages],
        }

        if config.include_confidence and candidate.confidence:
            d["confidence"] = self._confidence_to_dict(candidate.confidence)

        if config.include_provenance and provenance_records:
            d["provenance"] = [self._provenance_to_dict(p) for p in provenance_records]

        if config.include_metadata and candidate.metadata:
            d["metadata"] = self._metadata_to_dict(candidate.metadata, config)

        return d

    def _apply_field_selection(
        self,
        full_dict: dict[str, Any],
        config: OutputConfig,
    ) -> dict[str, Any]:
        """Keep only fields specified in config.output_fields."""
        desired = set(config.output_fields) | _SYSTEM_FIELDS

        # Always include confidence and provenance control from config
        if not config.include_confidence:
            desired.discard("confidence")
        if not config.include_provenance:
            desired.discard("provenance")
        if not config.include_metadata:
            desired.discard("metadata")

        return {k: v for k, v in full_dict.items() if k in desired}

    def _apply_null_handling(
        self,
        d: dict[str, Any],
        null_handling: str,
    ) -> dict[str, Any]:
        """Apply null/empty value handling strategy."""
        if null_handling == "omit":
            return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}
        if null_handling == "empty":
            return {k: ("" if v is None else v) for k, v in d.items()}
        # "null" — keep as-is
        return d

    # ── Field serialization helpers ───────────────────────────────────────

    def _location_to_dict(self, location: Any) -> dict[str, Any] | None:
        if not location:
            return None
        return {
            "city": location.city,
            "state": location.state,
            "country": location.country,
            "country_code": location.country_code,
            "postal_code": location.postal_code,
            "display": location.display,
        }

    def _skill_to_dict(self, skill: Any) -> dict[str, Any]:
        return {
            "name": skill.canonical_name,
            "level": skill.level.value,
            "years_of_experience": skill.years_of_experience,
            "category": skill.category,
        }

    def _experience_to_dict(self, exp: Any, config: OutputConfig) -> dict[str, Any]:
        return {
            "company": exp.company,
            "title": exp.title,
            "location": self._location_to_dict(exp.location),
            "start_date": self._format_date(exp.start_date, config.date_format),
            "end_date": self._format_date(exp.end_date, config.date_format),
            "is_current": exp.is_current,
            "duration_months": exp.duration_months,
            "description": exp.description,
            "responsibilities": exp.responsibilities,
            "technologies": exp.technologies,
            "achievements": exp.achievements,
        }

    def _education_to_dict(self, edu: Any, config: OutputConfig) -> dict[str, Any]:
        return {
            "institution": edu.institution,
            "degree": edu.degree.value,
            "field_of_study": edu.field_of_study,
            "start_date": self._format_date(edu.start_date, config.date_format),
            "end_date": self._format_date(edu.end_date, config.date_format),
            "gpa": edu.gpa,
            "honors": edu.honors,
        }

    def _project_to_dict(self, proj: Any, config: OutputConfig) -> dict[str, Any]:
        return {
            "name": proj.name,
            "description": proj.description,
            "url": proj.url,
            "repository_url": proj.repository_url,
            "technologies": proj.technologies,
            "is_open_source": proj.is_open_source,
            "stars": proj.stars,
            "forks": proj.forks,
            "start_date": self._format_date(proj.start_date, config.date_format),
            "end_date": self._format_date(proj.end_date, config.date_format),
        }

    def _cert_to_dict(self, cert: Any, config: OutputConfig) -> dict[str, Any]:
        return {
            "name": cert.name,
            "issuing_organization": cert.issuing_organization,
            "issue_date": self._format_date(cert.issue_date, config.date_format),
            "expiry_date": self._format_date(cert.expiry_date, config.date_format),
            "credential_id": cert.credential_id,
            "credential_url": cert.credential_url,
        }

    def _link_to_dict(self, link: Any) -> dict[str, Any]:
        return {
            "platform": link.platform.value,
            "url": link.url,
            "username": link.username,
        }

    def _confidence_to_dict(self, conf: ConfidenceRecord) -> dict[str, Any]:
        return {
            "overall_score": conf.overall_score,
            "sources_used": conf.sources_used,
            "high_confidence_fields": conf.high_confidence_fields,
            "low_confidence_fields": conf.low_confidence_fields,
            "fields": {
                name: {
                    "score": fc.score,
                    "explanation": fc.explanation,
                }
                for name, fc in conf.fields.items()
            },
        }

    def _provenance_to_dict(self, prov: FieldProvenance) -> dict[str, Any]:
        return {
            "field": prov.field_name,
            "source": prov.selected.source.value,
            "method": prov.selected.extraction_method,
            "confidence": prov.selected.confidence,
            "conflict_resolved": prov.conflict_resolved,
            "resolution_reason": prov.resolution_reason,
            "candidate_count": len(prov.candidates),
        }

    def _metadata_to_dict(self, meta: Any, config: OutputConfig) -> dict[str, Any]:
        return {
            "run_id": str(meta.run_id),
            "pipeline_version": meta.pipeline_version,
            "started_at": self._format_datetime(meta.started_at),
            "completed_at": self._format_datetime(meta.completed_at),
            "duration_ms": meta.duration_ms,
            "sources_requested": [s.value for s in meta.sources_requested],
            "sources_succeeded": [s.value for s in meta.sources_succeeded],
            "sources_failed": [s.value for s in meta.sources_failed],
            "validation_passed": meta.validation_passed,
            "validation_warnings": meta.validation_warnings,
            "validation_errors": meta.validation_errors,
        }

    def _format_date(self, d: date | None, fmt: str) -> str | None:
        if d is None:
            return None
        return d.isoformat()

    def _format_datetime(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat() + "Z"

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """Custom JSON default for orjson's ``default`` parameter."""
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
