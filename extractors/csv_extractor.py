"""
extractors.csv_extractor — Structured CSV source extractor.

Reads recruiter-formatted CSV files using Pandas (for robust CSV dialect
handling) and maps columns to ExtractedCandidate fields.

Why Pandas for CSV?
  - Handles encoding detection, mixed-type columns, and malformed CSVs better
    than the stdlib csv module.
  - Consistent NA handling (``pd.isna``).
  - Vectorized operations on large recruiter exports.

Column name resolution is case-insensitive and whitespace-tolerant (e.g.,
"First Name", "first_name", "FIRST NAME" all map to ``first_name``).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd

from extractors.base import BaseExtractor, ExtractorError
from models.extracted import ExtractedCandidate, RawExperience
from models.metadata import SourceType
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)

# ── Column alias map: canonical_field → [accepted column names] ──────────────
_COLUMN_ALIASES: dict[str, list[str]] = {
    "first_name": ["first_name", "first name", "firstname", "given_name", "given name"],
    "last_name": ["last_name", "last name", "lastname", "surname", "family_name", "family name"],
    "full_name": ["full_name", "full name", "name", "candidate_name", "candidate name"],
    "email": ["email", "email_address", "email address", "e-mail", "e_mail"],
    "phone": ["phone", "phone_number", "phone number", "mobile", "mobile_number", "cell", "telephone"],
    "location": ["location", "city", "address", "location_raw"],
    "summary": ["summary", "bio", "about", "profile", "overview", "objective"],
    "skills": ["skills", "skill_set", "skill set", "technologies", "tech_stack", "tech stack", "expertise"],
    "current_company": ["current_company", "current company", "company", "employer", "organization"],
    "current_title": ["current_title", "current title", "title", "job_title", "job title", "position", "role"],
    "linkedin_url": ["linkedin", "linkedin_url", "linkedin url", "linkedin_profile", "linkedin profile"],
    "github_url": ["github", "github_url", "github url", "github_profile"],
    "years_experience": ["years_experience", "years experience", "experience_years", "experience years", "years_of_experience", "yoe"],
}


def _build_column_map(columns: list[str]) -> dict[str, str]:
    """
    Build a mapping from canonical field name to actual DataFrame column name.

    Matching is case-insensitive and strips whitespace.
    """
    columns_lower = {c.lower().strip(): c for c in columns}
    result: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in columns_lower:
                result[canonical] = columns_lower[alias]
                break
    return result


def _safe_str(value: Any) -> str | None:
    """Convert a DataFrame cell value to str, handling NaN/None."""
    if pd.isna(value) if not isinstance(value, (list, dict)) else False:
        return None
    s = str(value).strip()
    return s if s and s.lower() not in {"nan", "none", "null", ""} else None


class CSVExtractor(BaseExtractor):
    """
    Extracts candidate data from recruiter-formatted CSV files.

    Supports:
      - Single-row CSV (one candidate per run)
      - Multi-row CSV (first row used; multiple rows reserved for batch processing)
      - Comma, semicolon, or tab-delimited files
      - UTF-8, Latin-1, and CP1252 encodings

    The extractor does NOT perform normalization — that is the responsibility
    of the normalizer modules downstream.
    """

    source_type = SourceType.CSV

    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from a CSV file.

        Parameters
        ----------
        source:
            Path to the CSV file.

        Raises
        ------
        ExtractorError
            If the file does not exist, cannot be parsed, or contains no rows.
        """
        path = Path(source)

        if not path.exists():
            raise ExtractorError(
                f"CSV file not found: {path}",
                source=self.source_type,
            )

        if not path.is_file():
            raise ExtractorError(
                f"Path is not a file: {path}",
                source=self.source_type,
            )

        with timed("csv_extraction", path=str(path)):
            return self._extract_from_path(path)

    def _extract_from_path(self, path: Path) -> ExtractedCandidate:
        """Internal extraction logic after path validation."""
        log.info("csv_extraction_start", path=str(path))

        df = self._read_csv(path)

        if df.empty:
            raise ExtractorError(
                f"CSV file is empty or contains only a header: {path}",
                source=self.source_type,
            )

        # Use the first row (batch processing is a future enhancement)
        row = df.iloc[0]
        col_map = _build_column_map(list(df.columns))

        log.debug(
            "csv_column_map",
            path=str(path),
            mapped_columns=list(col_map.keys()),
            total_columns=len(df.columns),
        )

        def get(field: str) -> str | None:
            col = col_map.get(field)
            return _safe_str(row[col]) if col and col in row.index else None

        # ── Parse skills ──────────────────────────────────────────────────
        skills_raw: list[str] = []
        skills_str = get("skills")
        if skills_str:
            # Support comma, semicolon, or pipe-separated skills
            for sep in ["|", ";", ","]:
                if sep in skills_str:
                    skills_raw = [s.strip() for s in skills_str.split(sep) if s.strip()]
                    break
            if not skills_raw:
                skills_raw = [skills_str]

        # ── Parse experience (from current company/title) ─────────────────
        experience: list[RawExperience] = []
        company = get("current_company")
        title = get("current_title")
        if company or title:
            experience.append(
                RawExperience(
                    company=company,
                    title=title,
                    is_current=True,
                )
            )

        # ── Parse social links ────────────────────────────────────────────
        social_links: list[dict[str, Any]] = []
        linkedin = get("linkedin_url")
        if linkedin:
            social_links.append({"platform": "linkedin", "url": linkedin})
        github_url = get("github_url")
        if github_url:
            social_links.append({"platform": "github", "url": github_url})

        # ── Parse years of experience ─────────────────────────────────────
        years_exp: float | None = None
        years_raw = get("years_experience")
        if years_raw:
            try:
                years_exp = float(years_raw.split()[0])
            except (ValueError, IndexError):
                log.debug("csv_years_exp_parse_failed", raw=years_raw)

        extracted = ExtractedCandidate(
            source=self.source_type,
            raw_path=str(path),
            full_name=get("full_name"),
            first_name=get("first_name"),
            last_name=get("last_name"),
            emails=[e for e in [get("email")] if e],
            phones=[p for p in [get("phone")] if p],
            location_raw=get("location"),
            summary=get("summary"),
            skills_raw=skills_raw,
            experience=experience,
            social_links=social_links,
            years_of_experience=years_exp,
        )

        log.info(
            "csv_extraction_complete",
            path=str(path),
            name=extracted.full_name or f"{extracted.first_name} {extracted.last_name}",
            emails=len(extracted.emails),
            skills=len(extracted.skills_raw),
        )

        return extracted

    def _read_csv(self, path: Path) -> pd.DataFrame:
        """
        Attempt to read CSV with multiple encodings and delimiter detection.

        Raises ExtractorError if all attempts fail.
        """
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        separators = [",", ";", "\t", "|"]

        for encoding in encodings:
            try:
                for sep in separators:
                    try:
                        df = pd.read_csv(
                            path,
                            encoding=encoding,
                            sep=sep,
                            skipinitialspace=True,
                            dtype=str,
                            keep_default_na=False,
                            na_values=["", "NA", "N/A", "NULL", "None", "nan"],
                        )
                        if len(df.columns) > 1:
                            log.debug(
                                "csv_read_success",
                                encoding=encoding,
                                separator=repr(sep),
                                columns=len(df.columns),
                                rows=len(df),
                            )
                            return df
                    except pd.errors.ParserError:
                        continue
            except UnicodeDecodeError:
                continue

        raise ExtractorError(
            f"Unable to parse CSV file with any supported encoding/delimiter: {path}",
            source=self.source_type,
        )
