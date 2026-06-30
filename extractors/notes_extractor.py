"""
extractors.notes_extractor — Recruiter notes TXT file extractor.

Processes free-text recruiter notes to extract structured candidate data
using regex-based pattern matching.

Recruiter notes are the most unstructured source.  They typically contain:
  - Direct mentions of candidate name, contact info
  - Free-form skill mentions
  - Subjective assessments
  - Meeting notes with dates

Extraction approach:
  - Pattern-match contact information (email, phone) as in PDF extraction
  - Named entity heuristics for name detection
  - Keyword scanning for skills mentioned in notes

Because notes are highly variable, this extractor has the lowest confidence
weight (0.70) and primarily serves as a supplementary source.
"""

from __future__ import annotations

import re
from pathlib import Path

from extractors.base import BaseExtractor, ExtractorError
from models.extracted import ExtractedCandidate
from models.metadata import SourceType
from normalizers.skill_normalizer import SKILL_ALIASES
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)

# Contact patterns (same as PDF extractor — shared in production would live in utils)
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?:(?:\+?1\s?)?(?:\(?\d{3}\)?)[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"|\+\d{1,3}[\s.\-]?\d{2,4}[\s.\-]?\d{2,4}[\s.\-]?\d{2,9})",
)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w\-]+", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/[\w\-]+", re.IGNORECASE)

# Name patterns: "Candidate: John Doe" or "Name: John Doe"
_NAME_LABEL_RE = re.compile(
    r"(?:candidate|name|candidate\s+name)\s*:\s*([A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){1,3})",
    re.IGNORECASE,
)

# Location patterns: "Location: San Francisco, CA"
_LOCATION_LABEL_RE = re.compile(
    r"(?:location|city|based\s+in|located\s+in)\s*:\s*([^\n,]+(?:,\s*[^\n]+)?)",
    re.IGNORECASE,
)

# Years of experience: "5 years of experience", "10+ years"
_YEARS_EXP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\+?\s*years?\s+(?:of\s+)?(?:experience|exp)",
    re.IGNORECASE,
)

# Build a set of all known skill terms for scanning
_ALL_SKILL_TERMS: set[str] = set()
for _canonical_skill, _aliases_list in SKILL_ALIASES.items():
    _ALL_SKILL_TERMS.add(_canonical_skill.lower())
    for _alias in _aliases_list:
        _ALL_SKILL_TERMS.add(_alias.lower())


class NotesExtractor(BaseExtractor):
    """
    Extracts candidate data from recruiter notes text files.

    Supported encodings: UTF-8, Latin-1, CP1252 (auto-detected).
    Notes can be plain text (.txt) or Markdown (.md).
    """

    source_type = SourceType.NOTES

    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from a recruiter notes text file.

        Parameters
        ----------
        source:
            Path to the .txt or .md notes file.

        Raises
        ------
        ExtractorError
            If the file does not exist or cannot be read.
        """
        path = Path(source)

        if not path.exists():
            raise ExtractorError(
                f"Recruiter notes file not found: {path}",
                source=self.source_type,
            )

        with timed("notes_extraction", path=str(path)):
            return self._extract_from_path(path)

    def _extract_from_path(self, path: Path) -> ExtractedCandidate:
        log.info("notes_extraction_start", path=str(path))

        text = self._read_file(path)
        if not text or len(text.strip()) < 10:
            raise ExtractorError(
                f"Recruiter notes file is empty: {path}",
                source=self.source_type,
            )

        # ── Contact ───────────────────────────────────────────────────────
        emails = list(set(_EMAIL_RE.findall(text)))
        phones = list(set(_PHONE_RE.findall(text)))

        # ── Name ──────────────────────────────────────────────────────────
        full_name: str | None = None
        name_match = _NAME_LABEL_RE.search(text)
        if name_match:
            full_name = name_match.group(1).strip()

        # ── Location ──────────────────────────────────────────────────────
        location_raw: str | None = None
        loc_match = _LOCATION_LABEL_RE.search(text)
        if loc_match:
            location_raw = loc_match.group(1).strip()

        # ── Years of experience ───────────────────────────────────────────
        years_exp: float | None = None
        yoe_match = _YEARS_EXP_RE.search(text)
        if yoe_match:
            try:
                years_exp = float(yoe_match.group(1))
            except ValueError:
                pass

        # ── Skills (keyword scanning) ─────────────────────────────────────
        skills_raw = self._scan_skills(text)

        # ── Social links ──────────────────────────────────────────────────
        social_links = []
        linkedin_matches = _LINKEDIN_RE.findall(text)
        for match in linkedin_matches:
            social_links.append({"platform": "linkedin", "url": f"https://{match}"})
        github_matches = _GITHUB_RE.findall(text)
        for match in github_matches:
            social_links.append({"platform": "github", "url": f"https://{match}"})

        # ── Summary (full text as notes summary) ──────────────────────────
        summary = text.strip()[:2000] if text.strip() else None

        extracted = ExtractedCandidate(
            source=self.source_type,
            raw_path=str(path),
            full_name=full_name,
            emails=emails,
            phones=phones,
            location_raw=location_raw,
            summary=summary,
            skills_raw=skills_raw,
            social_links=social_links,
            years_of_experience=years_exp,
        )

        log.info(
            "notes_extraction_complete",
            path=str(path),
            name=extracted.full_name,
            emails=len(emails),
            skills=len(skills_raw),
        )

        return extracted

    def _read_file(self, path: Path) -> str:
        """Read file with encoding fallbacks."""
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue

        raise ExtractorError(
            f"Cannot decode recruiter notes file with any supported encoding: {path}",
            source=self.source_type,
        )

    def _scan_skills(self, text: str) -> list[str]:
        """
        Scan text for known skill terms using word-boundary matching.

        This is O(n * m) where n = text tokens and m = skill terms.
        For production scale, this would use Aho-Corasick or a prebuilt trie.
        """
        text_lower = text.lower()
        found: list[str] = []
        seen: set[str] = set()

        for term in _ALL_SKILL_TERMS:
            # Word-boundary search to avoid matching "Go" inside "Google"
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, text_lower):
                if term not in seen:
                    seen.add(term)
                    found.append(term)

        return found
