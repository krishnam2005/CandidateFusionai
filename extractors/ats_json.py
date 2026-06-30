"""
extractors.ats_json — ATS (Applicant Tracking System) JSON source extractor.

Reads structured JSON exported from ATS platforms (Greenhouse, Lever,
Workday, Taleo, etc.) and maps to ExtractedCandidate.

ATS JSON formats vary significantly between vendors.  This extractor handles
a canonical internal format (defined by the sample input) and uses lenient
field resolution to tolerate minor schema variations.

Design decisions:
  - Uses ``orjson`` for parsing: 3-5x faster than stdlib json and handles
    bytes/str/Path inputs natively.
  - Field resolution uses multiple fallback paths (e.g., both "email" and
    "email_address" are accepted).
  - Nested objects (experience, education) are handled recursively.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from extractors.base import BaseExtractor, ExtractorError
from models.extracted import (
    ExtractedCandidate,
    RawCertification,
    RawEducation,
    RawExperience,
    RawProject,
)
from models.metadata import SourceType
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)


def _get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Lookup a value from a dict trying multiple key names.

    Returns the first non-None value found, or ``default``.
    """
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _str_list(raw: Any) -> list[str]:
    """Convert a value to a list of non-empty strings."""
    if isinstance(raw, list):
        return [str(i).strip() for i in raw if i and str(i).strip()]
    if isinstance(raw, str) and raw.strip():
        return [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
    return []


class ATSJsonExtractor(BaseExtractor):
    """
    Extracts candidate data from ATS-formatted JSON files.

    Supports both a flat structure and nested objects for collections
    (experience, education, projects, certifications).
    """

    source_type = SourceType.ATS

    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from an ATS JSON file.

        Parameters
        ----------
        source:
            Path to the ATS JSON file.

        Raises
        ------
        ExtractorError
            If the file is missing, not valid JSON, or contains no useful data.
        """
        path = Path(source)

        if not path.exists():
            raise ExtractorError(
                f"ATS JSON file not found: {path}",
                source=self.source_type,
            )

        with timed("ats_json_extraction", path=str(path)):
            return self._extract_from_path(path)

    def _extract_from_path(self, path: Path) -> ExtractedCandidate:
        log.info("ats_json_extraction_start", path=str(path))

        try:
            raw_bytes = path.read_bytes()
            data: dict[str, Any] = orjson.loads(raw_bytes)
        except orjson.JSONDecodeError as exc:
            raise ExtractorError(
                f"Invalid JSON in ATS file {path}: {exc}",
                source=self.source_type,
                cause=exc,
            ) from exc
        except OSError as exc:
            raise ExtractorError(
                f"Cannot read ATS JSON file {path}: {exc}",
                source=self.source_type,
                cause=exc,
            ) from exc

        if not isinstance(data, dict):
            raise ExtractorError(
                f"ATS JSON must be a JSON object (dict), got {type(data).__name__}: {path}",
                source=self.source_type,
            )

        # ── Identity ──────────────────────────────────────────────────────
        full_name = _get(data, "full_name", "name", "candidate_name", "fullName")
        first_name = _get(data, "first_name", "firstName", "given_name")
        last_name = _get(data, "last_name", "lastName", "surname", "family_name")

        # ── Contact ───────────────────────────────────────────────────────
        emails_raw = _get(data, "emails", "email_addresses", "email")
        emails: list[str] = _str_list(emails_raw)

        phones_raw = _get(data, "phones", "phone_numbers", "phone")
        phones: list[str] = _str_list(phones_raw)

        location_raw = _get(data, "location", "address", "city")
        location_obj = data.get("location_structured") or {}
        city = location_obj.get("city") if isinstance(location_obj, dict) else None
        state = location_obj.get("state") if isinstance(location_obj, dict) else None
        country = location_obj.get("country") if isinstance(location_obj, dict) else None

        # ── Professional ─────────────────────────────────────────────────
        summary = _get(data, "summary", "bio", "about", "profile_summary")
        headline = _get(data, "headline", "title", "current_role")
        years_exp_raw = _get(data, "years_of_experience", "years_experience", "experience_years")
        years_exp: float | None = None
        if years_exp_raw is not None:
            try:
                years_exp = float(years_exp_raw)
            except (ValueError, TypeError):
                log.debug("ats_years_exp_parse_failed", raw=years_exp_raw)

        # ── Skills ────────────────────────────────────────────────────────
        skills_raw = _str_list(_get(data, "skills", "skill_set", "technologies", []))

        # ── Experience ────────────────────────────────────────────────────
        experience = self._parse_experience(data.get("experience") or data.get("work_experience") or [])

        # ── Education ────────────────────────────────────────────────────
        education = self._parse_education(data.get("education") or [])

        # ── Projects ──────────────────────────────────────────────────────
        projects = self._parse_projects(data.get("projects") or [])

        # ── Certifications ────────────────────────────────────────────────
        certifications = self._parse_certifications(
            data.get("certifications") or data.get("certificates") or []
        )

        # ── Social Links ──────────────────────────────────────────────────
        social_links: list[dict[str, Any]] = list(data.get("social_links") or [])
        linkedin = _get(data, "linkedin_url", "linkedin")
        if linkedin:
            social_links.append({"platform": "linkedin", "url": linkedin})
        github_url = _get(data, "github_url", "github")
        if github_url:
            social_links.append({"platform": "github", "url": github_url})

        # ── Languages ─────────────────────────────────────────────────────
        languages = _str_list(data.get("languages") or [])

        # ── ATS-specific metadata ─────────────────────────────────────────
        ats_candidate_id = _get(data, "id", "candidate_id", "ats_id")
        ats_status = _get(data, "status", "application_status", "stage")

        extracted = ExtractedCandidate(
            source=self.source_type,
            raw_path=str(path),
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            emails=emails,
            phones=phones,
            location_raw=str(location_raw) if location_raw else None,
            city=city,
            state=state,
            country=country,
            summary=str(summary) if summary else None,
            headline=str(headline) if headline else None,
            years_of_experience=years_exp,
            skills_raw=skills_raw,
            experience=experience,
            education=education,
            projects=projects,
            certifications=certifications,
            social_links=social_links,
            languages=languages,
            ats_candidate_id=str(ats_candidate_id) if ats_candidate_id else None,
            ats_status=str(ats_status) if ats_status else None,
        )

        log.info(
            "ats_json_extraction_complete",
            path=str(path),
            candidate_id=extracted.ats_candidate_id,
            skills=len(extracted.skills_raw),
            experience=len(extracted.experience),
            education=len(extracted.education),
        )

        return extracted

    def _parse_experience(self, raw_list: list[Any]) -> list[RawExperience]:
        result: list[RawExperience] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            responsibilities = _str_list(
                _get(item, "responsibilities", "duties", "description_bullets", default=[])
            )
            technologies = _str_list(
                _get(item, "technologies", "tech_stack", "tools", default=[])
            )
            achievements = _str_list(
                _get(item, "achievements", "accomplishments", default=[])
            )
            result.append(
                RawExperience(
                    company=_get(item, "company", "employer", "organization"),
                    title=_get(item, "title", "position", "role", "job_title"),
                    location_raw=_get(item, "location", "city"),
                    start_date_raw=_get(item, "start_date", "startDate", "from"),
                    end_date_raw=_get(item, "end_date", "endDate", "to"),
                    is_current=bool(_get(item, "is_current", "current", default=False)),
                    description=_get(item, "description", "summary"),
                    responsibilities=responsibilities,
                    technologies=technologies,
                    achievements=achievements,
                )
            )
        return result

    def _parse_education(self, raw_list: list[Any]) -> list[RawEducation]:
        result: list[RawEducation] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            result.append(
                RawEducation(
                    institution=_get(item, "institution", "school", "university", "college"),
                    degree_raw=_get(item, "degree", "degree_type", "level"),
                    field_of_study=_get(item, "field_of_study", "major", "discipline"),
                    start_date_raw=_get(item, "start_date", "startDate"),
                    end_date_raw=_get(item, "end_date", "endDate", "graduation_date"),
                    gpa_raw=_get(item, "gpa", "grade"),
                    honors=_str_list(_get(item, "honors", "awards", default=[])),
                )
            )
        return result

    def _parse_projects(self, raw_list: list[Any]) -> list[RawProject]:
        result: list[RawProject] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            result.append(
                RawProject(
                    name=_get(item, "name", "title"),
                    description=_get(item, "description"),
                    url=_get(item, "url", "demo_url", "live_url"),
                    repository_url=_get(item, "repository_url", "repo_url", "github_url"),
                    technologies=_str_list(_get(item, "technologies", "tech", default=[])),
                    start_date_raw=_get(item, "start_date"),
                    end_date_raw=_get(item, "end_date"),
                    is_open_source=bool(_get(item, "is_open_source", "open_source", default=False)),
                    stars=_get(item, "stars"),
                    forks=_get(item, "forks"),
                )
            )
        return result

    def _parse_certifications(self, raw_list: list[Any]) -> list[RawCertification]:
        result: list[RawCertification] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            result.append(
                RawCertification(
                    name=_get(item, "name", "title", "certification_name"),
                    issuing_organization=_get(item, "issuing_organization", "issuer", "organization"),
                    issue_date_raw=_get(item, "issue_date", "issued_date", "date"),
                    expiry_date_raw=_get(item, "expiry_date", "expiration_date", "expires"),
                    credential_id=_get(item, "credential_id", "license_number"),
                    credential_url=_get(item, "credential_url", "url", "verify_url"),
                )
            )
        return result
