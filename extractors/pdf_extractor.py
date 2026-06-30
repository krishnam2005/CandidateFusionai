"""
extractors.pdf_extractor — Resume PDF text extraction and parsing.

Two-library strategy:
  Primary:  pdfplumber — provides structured text blocks with position data,
            excellent for columnar layouts and tables.
  Fallback: PyMuPDF (fitz) — faster and more resilient on malformed PDFs;
            used when pdfplumber raises an exception or produces no text.

Why both libraries?
  - pdfplumber excels at layout-preserving extraction and table detection.
  - PyMuPDF handles encrypted PDFs (with empty passwords) and corrupt files
    better than pdfplumber.
  - Combining them gives the highest extraction success rate across the wide
    variety of resume formats seen in production.

Parsing strategy for unstructured resume text:
  - Section-based heuristics using regex anchors (EXPERIENCE, EDUCATION, etc.)
  - Named entity patterns for contact information (email, phone, LinkedIn)
  - Skills extraction from a skill section or bullet points

This is NOT a full NLP pipeline.  For production accuracy, integrate a
fine-tuned NER model (e.g., spaCy with a custom resume model) behind the
BaseExtractor interface.
"""

from __future__ import annotations

import re
from pathlib import Path

from extractors.base import BaseExtractor, ExtractorError
from models.extracted import ExtractedCandidate, RawEducation, RawExperience
from models.metadata import SourceType
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)

# ── Contact extraction regexes ────────────────────────────────────────────────
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
_URL_RE = re.compile(r"https?://[^\s,<>\"']+", re.IGNORECASE)

# ── Section header detection patterns ─────────────────────────────────────────
_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "experience": re.compile(
        r"^\s*(?:work\s+)?(?:experience|employment|work\s+history|professional\s+background|career)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "education": re.compile(
        r"^\s*(?:education|academic|academic\s+background|qualifications|educational\s+background)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "skills": re.compile(
        r"^\s*(?:skills?|technical\s+skills?|core\s+competenc(?:y|ies)|expertise|technologies|proficiencies)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "summary": re.compile(
        r"^\s*(?:summary|profile|about\s+me|professional\s+summary|objective|career\s+objective|executive\s+summary)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "projects": re.compile(
        r"^\s*(?:projects?|personal\s+projects?|side\s+projects?|open\s+source)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "certifications": re.compile(
        r"^\s*(?:certifications?|licenses?|credentials?|certificates?)\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# ── Degree keyword map ────────────────────────────────────────────────────────
_DEGREE_KEYWORDS = {
    "ph.d": "phd", "phd": "phd", "doctor": "phd",
    "master": "master", "m.s": "master", "m.sc": "master", "mba": "mba",
    "bachelor": "bachelor", "b.s": "bachelor", "b.sc": "bachelor", "b.a": "bachelor",
    "associate": "associate", "a.s": "associate",
    "bootcamp": "bootcamp", "boot camp": "bootcamp",
    "high school": "high_school", "diploma": "high_school",
}

# Date range pattern for experience entries
_DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s,]+\d{4}|\d{4})"
    r"\s*[–\-—]\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s,]+\d{4}|\d{4}|[Pp]resent|[Cc]urrent|[Nn]ow)",
    re.IGNORECASE,
)


class PDFExtractor(BaseExtractor):
    """
    Extracts candidate data from PDF resume files.

    Uses pdfplumber as the primary extractor with PyMuPDF as a fallback.
    Text is parsed with heuristic regex patterns to identify sections,
    contact information, and skills.
    """

    source_type = SourceType.RESUME

    def __init__(
        self,
        max_pages: int = 50,
        strategy: str = "pdfplumber",
    ) -> None:
        self._max_pages = max_pages
        self._strategy = strategy

    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from a PDF resume.

        Parameters
        ----------
        source:
            Path to the PDF file.

        Raises
        ------
        ExtractorError
            If the file does not exist or cannot be read by either library.
        """
        path = Path(source)

        if not path.exists():
            raise ExtractorError(
                f"Resume PDF not found: {path}",
                source=self.source_type,
            )

        if path.suffix.lower() != ".pdf":
            log.warning("pdf_extractor_non_pdf_extension", path=str(path))

        with timed("pdf_extraction", path=str(path), strategy=self._strategy):
            return self._extract_from_path(path)

    def _extract_from_path(self, path: Path) -> ExtractedCandidate:
        log.info("pdf_extraction_start", path=str(path))

        text = self._extract_text(path)
        if not text or len(text.strip()) < 50:
            raise ExtractorError(
                f"PDF produced insufficient text (may be image-based or empty): {path}",
                source=self.source_type,
            )

        log.debug("pdf_text_extracted", path=str(path), char_count=len(text))

        # ── Contact information ───────────────────────────────────────────
        emails = list(set(_EMAIL_RE.findall(text)))
        phones = list(set(_PHONE_RE.findall(text)))

        # ── Social links ──────────────────────────────────────────────────
        social_links = []
        linkedin_matches = _LINKEDIN_RE.findall(text)
        for match in linkedin_matches:
            social_links.append({"platform": "linkedin", "url": f"https://{match}"})

        github_matches = _GITHUB_RE.findall(text)
        for match in github_matches:
            social_links.append({"platform": "github", "url": f"https://{match}"})

        # ── Section-based parsing ─────────────────────────────────────────
        sections = self._split_sections(text)

        name = self._extract_name(text, emails)
        summary = self._clean_section(sections.get("summary", ""))
        skills_raw = self._parse_skills(sections.get("skills", ""))
        experience = self._parse_experience(sections.get("experience", ""))
        education = self._parse_education(sections.get("education", ""))

        extracted = ExtractedCandidate(
            source=self.source_type,
            raw_path=str(path),
            full_name=name,
            emails=emails,
            phones=phones,
            summary=summary,
            skills_raw=skills_raw,
            experience=experience,
            education=education,
            social_links=social_links,
        )

        log.info(
            "pdf_extraction_complete",
            path=str(path),
            name=extracted.full_name,
            emails=len(emails),
            phones=len(phones),
            skills=len(skills_raw),
            experience=len(experience),
            education=len(education),
        )

        return extracted

    def _extract_text(self, path: Path) -> str:
        """Extract raw text using pdfplumber with PyMuPDF fallback."""
        if self._strategy == "pdfplumber":
            text = self._extract_with_pdfplumber(path)
            if text:
                return text
            log.warning("pdfplumber_fallback_to_pymupdf", path=str(path))
            return self._extract_with_pymupdf(path)
        else:
            text = self._extract_with_pymupdf(path)
            if text:
                return text
            return self._extract_with_pdfplumber(path)

    def _extract_with_pdfplumber(self, path: Path) -> str:
        """Extract text using pdfplumber."""
        try:
            import pdfplumber

            pages_text: list[str] = []
            with pdfplumber.open(str(path)) as pdf:
                for i, page in enumerate(pdf.pages[: self._max_pages]):
                    page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                    if page_text:
                        pages_text.append(page_text)
            return "\n".join(pages_text)
        except Exception as exc:
            log.warning(
                "pdfplumber_extraction_failed",
                path=str(path),
                error=str(exc),
            )
            return ""

    def _extract_with_pymupdf(self, path: Path) -> str:
        """Extract text using PyMuPDF (fitz)."""
        try:
            import fitz  # PyMuPDF

            pages_text: list[str] = []
            with fitz.open(str(path)) as doc:
                for page_num in range(min(len(doc), self._max_pages)):
                    page = doc[page_num]
                    pages_text.append(page.get_text("text"))
            return "\n".join(pages_text)
        except Exception as exc:
            log.warning(
                "pymupdf_extraction_failed",
                path=str(path),
                error=str(exc),
            )
            return ""

    def _split_sections(self, text: str) -> dict[str, str]:
        """
        Split resume text into named sections using header detection.

        Returns a dict of section_name → section_content.
        """
        lines = text.split("\n")
        sections: dict[str, str] = {}
        current_section: str | None = None
        current_lines: list[str] = []

        for line in lines:
            matched_section: str | None = None
            for section_name, pattern in _SECTION_PATTERNS.items():
                if pattern.match(line):
                    matched_section = section_name
                    break

            if matched_section:
                # Save previous section
                if current_section is not None:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = matched_section
                current_lines = []
            else:
                if current_section is not None:
                    current_lines.append(line)
                # Lines before any section header go to "header"
                elif line.strip():
                    sections.setdefault("header", "")
                    sections["header"] += line + "\n"

        # Save last section
        if current_section is not None:
            sections[current_section] = "\n".join(current_lines).strip()

        return sections

    def _extract_name(self, text: str, emails: list[str]) -> str | None:
        """
        Attempt to extract the candidate's name from the first lines of the resume.

        Heuristic: the name is likely on one of the first 3 non-empty lines,
        is title-cased, and does not look like an email, phone, or URL.
        """
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        email_domains = {e.split("@")[-1] for e in emails}

        for line in lines[:5]:
            # Skip lines that look like contact info
            if _EMAIL_RE.search(line):
                continue
            if _PHONE_RE.search(line):
                continue
            if _URL_RE.search(line):
                continue
            # Skip section headers
            if any(p.match(line) for p in _SECTION_PATTERNS.values()):
                continue
            # Name heuristic: 2-4 words, title-cased, no special chars
            words = line.split()
            if 1 < len(words) <= 4:
                if all(w[0].isupper() for w in words if w):
                    return line
        return None

    def _parse_skills(self, section_text: str) -> list[str]:
        """Extract skills from a skills section."""
        if not section_text:
            return []

        skills: list[str] = []
        for line in section_text.split("\n"):
            line = line.strip(" •·-–—*►▪")
            if not line:
                continue
            # Each line may be comma or pipe-separated
            for sep in [",", "|", "•", ";", "/"]:
                if sep in line:
                    skills.extend(s.strip(" •·-–—*►▪") for s in line.split(sep))
                    break
            else:
                skills.append(line)

        return [s for s in skills if s and len(s) > 1 and len(s) < 80]

    def _parse_experience(self, section_text: str) -> list[RawExperience]:
        """Parse work experience entries from section text."""
        if not section_text:
            return []

        entries: list[RawExperience] = []
        blocks = re.split(r"\n{2,}", section_text)

        for block in blocks:
            if not block.strip():
                continue

            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            # First line → usually "Company | Title" or "Title at Company"
            company: str | None = None
            title: str | None = None
            start_date_raw: str | None = None
            end_date_raw: str | None = None
            is_current = False

            first_line = lines[0]

            # Company | Title
            if "|" in first_line:
                parts = first_line.split("|", 1)
                company = parts[0].strip()
                title = parts[1].strip()
            elif " at " in first_line.lower():
                parts = re.split(r" at ", first_line, 1, flags=re.IGNORECASE)
                title = parts[0].strip()
                company = parts[1].strip()
            else:
                company = first_line

            # Second line → often date range
            if len(lines) > 1:
                date_match = _DATE_RANGE_RE.search(lines[1])
                if date_match:
                    start_date_raw = date_match.group(1)
                    end_date_raw = date_match.group(2)
                    is_current = end_date_raw.lower() in {"present", "current", "now"}
                else:
                    # May be the title
                    if not title:
                        title = lines[1]

            # Remaining lines → description/responsibilities
            desc_lines = lines[2:] if len(lines) > 2 else []
            description = " ".join(desc_lines) if desc_lines else None

            entries.append(
                RawExperience(
                    company=company,
                    title=title,
                    start_date_raw=start_date_raw,
                    end_date_raw=end_date_raw,
                    is_current=is_current,
                    description=description,
                )
            )

        return entries

    def _parse_education(self, section_text: str) -> list[RawEducation]:
        """Parse education entries from section text."""
        if not section_text:
            return []

        entries: list[RawEducation] = []
        blocks = re.split(r"\n{2,}", section_text)

        for block in blocks:
            if not block.strip():
                continue

            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            institution = lines[0] if lines else None
            degree_raw: str | None = None
            field_of_study: str | None = None
            end_date_raw: str | None = None

            # Look for degree keywords in remaining lines
            for line in lines[1:]:
                line_lower = line.lower()
                for kw in _DEGREE_KEYWORDS:
                    if kw in line_lower:
                        degree_raw = line
                        # Try to extract field of study (text after "in" or ",")
                        for sep in [" in ", ", "]:
                            if sep in line_lower:
                                field_of_study = line.split(sep, 1)[-1].strip()
                                break
                        break

                # Look for year
                year_match = re.search(r"\b(19|20)\d{2}\b", line)
                if year_match and not end_date_raw:
                    end_date_raw = year_match.group(0)

            entries.append(
                RawEducation(
                    institution=institution,
                    degree_raw=degree_raw,
                    field_of_study=field_of_study,
                    end_date_raw=end_date_raw,
                )
            )

        return entries

    @staticmethod
    def _clean_section(text: str | None) -> str | None:
        """Clean up extracted section text."""
        if not text:
            return None
        cleaned = " ".join(text.split())
        return cleaned if cleaned else None
