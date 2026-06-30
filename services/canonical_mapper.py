"""
services.canonical_mapper — Maps ExtractedCandidate to canonical Candidate model.

The canonical mapper is the bridge between the raw extraction layer and the
canonical data model.  It is responsible for:

  1. Type coercion: converting raw strings to typed values (dates, enums, etc.)
  2. Normalization: applying all normalizer modules to clean the data
  3. Model construction: building canonical domain objects (Skill, Experience, etc.)

The mapper does NOT merge data from multiple sources — that is the role of
the MergeEngine.  It processes one ExtractedCandidate at a time.

Design note on normalization placement:
  Normalization happens here (mapper) rather than in extractors because:
  - Extractors should have a single concern: raw data acquisition.
  - If normalization logic changes, only the mapper needs updating.
  - Multiple extractors can share the same normalization logic via the mapper.
"""

from __future__ import annotations

from datetime import date

from models.candidate import (
    Candidate,
    Certification,
    Education,
    EducationDegree,
    Experience,
    Language,
    Location,
    Project,
    Skill,
    SocialLink,
    SocialPlatform,
)
from models.extracted import ExtractedCandidate, RawCertification, RawEducation, RawExperience, RawProject
from normalizers.date_normalizer import DateNormalizer
from normalizers.email_normalizer import EmailNormalizer
from normalizers.location_normalizer import LocationNormalizer
from normalizers.phone_normalizer import PhoneNormalizer
from normalizers.skill_normalizer import SkillNormalizer
from normalizers.text_normalizer import TextNormalizer
from normalizers.url_normalizer import UrlNormalizer
from utils.logging import get_logger

log = get_logger(__name__)

# ── Degree keyword → EducationDegree enum ────────────────────────────────────
_DEGREE_MAP: dict[str, EducationDegree] = {
    "phd": EducationDegree.PHD,
    "ph.d": EducationDegree.PHD,
    "doctor": EducationDegree.PHD,
    "mba": EducationDegree.MBA,
    "master": EducationDegree.MASTER,
    "m.s": EducationDegree.MASTER,
    "m.sc": EducationDegree.MASTER,
    "ms ": EducationDegree.MASTER,
    "bachelor": EducationDegree.BACHELOR,
    "b.s": EducationDegree.BACHELOR,
    "b.sc": EducationDegree.BACHELOR,
    "b.a": EducationDegree.BACHELOR,
    "bs ": EducationDegree.BACHELOR,
    "ba ": EducationDegree.BACHELOR,
    "associate": EducationDegree.ASSOCIATE,
    "a.s": EducationDegree.ASSOCIATE,
    "bootcamp": EducationDegree.BOOTCAMP,
    "boot camp": EducationDegree.BOOTCAMP,
    "high school": EducationDegree.HIGH_SCHOOL,
    "diploma": EducationDegree.HIGH_SCHOOL,
    "certification": EducationDegree.CERTIFICATION,
    "certificate": EducationDegree.CERTIFICATION,
}


def _parse_degree(raw: str | None) -> EducationDegree:
    """Map a raw degree string to the canonical EducationDegree enum."""
    if not raw:
        return EducationDegree.UNKNOWN
    lower = raw.lower()
    for keyword, degree in _DEGREE_MAP.items():
        if keyword in lower:
            return degree
    return EducationDegree.OTHER


def _parse_gpa(raw: str | None) -> float | None:
    """Parse a GPA string like "3.8/4.0" or "3.8" into a float."""
    if not raw:
        return None
    cleaned = raw.split("/")[0].strip()
    try:
        gpa = float(cleaned)
        if 0.0 <= gpa <= 4.0:
            return gpa
    except ValueError:
        pass
    return None


class CanonicalMapper:
    """
    Transforms an ExtractedCandidate into a canonical Candidate model.

    Applies all normalization rules and type coercions.  Each method is
    single-responsibility for a specific field or collection.
    """

    def map(self, extracted: ExtractedCandidate) -> Candidate:
        """
        Map an ExtractedCandidate to a Candidate model.

        This is the primary entry point.  All field mapping is delegated
        to focused private methods.
        """
        log.debug(
            "canonical_mapping_start",
            source=extracted.source,
            raw_path=extracted.raw_path,
        )

        # ── Name ──────────────────────────────────────────────────────────
        full_name = TextNormalizer.normalize_name(extracted.full_name)
        first_name = TextNormalizer.normalize_name(extracted.first_name)
        last_name = TextNormalizer.normalize_name(extracted.last_name)

        # Infer full name from parts if missing
        if not full_name and (first_name or last_name):
            parts = [p for p in [first_name, last_name] if p]
            full_name = " ".join(parts)

        # Infer parts from full name if missing
        if full_name and not first_name and not last_name:
            first_name, _, last_name = TextNormalizer.split_name(full_name)

        # ── Contact ───────────────────────────────────────────────────────
        emails = EmailNormalizer.normalize_list(extracted.emails)
        phones = PhoneNormalizer.normalize_list(extracted.phones)

        # ── Location ──────────────────────────────────────────────────────
        location = self._map_location(extracted)

        # ── Summary ───────────────────────────────────────────────────────
        summary = TextNormalizer.truncate(TextNormalizer.clean(extracted.summary), 3000)
        headline = TextNormalizer.clean(extracted.headline)

        # ── Skills ────────────────────────────────────────────────────────
        skills = self._map_skills(extracted.skills_raw)

        # ── Experience ────────────────────────────────────────────────────
        experience = [self._map_experience(e) for e in extracted.experience]

        # ── Education ────────────────────────────────────────────────────
        education = [self._map_education(e) for e in extracted.education]

        # ── Projects ──────────────────────────────────────────────────────
        projects = [self._map_project(p) for p in extracted.projects]

        # ── Certifications ────────────────────────────────────────────────
        certifications = [self._map_certification(c) for c in extracted.certifications]

        # ── Social Links ──────────────────────────────────────────────────
        social_links = self._map_social_links(extracted.social_links)

        # ── Languages ─────────────────────────────────────────────────────
        languages = self._map_languages(extracted.languages)

        candidate = Candidate(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            emails=emails,
            phones=phones,
            location=location,
            summary=summary,
            headline=headline,
            years_of_experience=extracted.years_of_experience,
            skills=skills,
            experience=experience,
            education=education,
            projects=projects,
            certifications=certifications,
            social_links=social_links,
            languages=languages,
        )

        log.debug(
            "canonical_mapping_complete",
            source=extracted.source,
            full_name=candidate.full_name,
            skills=len(candidate.skills),
            experience=len(candidate.experience),
        )

        return candidate

    def _map_location(self, extracted: ExtractedCandidate) -> Location | None:
        """Map location fields from an ExtractedCandidate."""
        # If structured fields are available, prefer them
        if extracted.city or extracted.state or extracted.country:
            return Location(
                city=TextNormalizer.clean(extracted.city),
                state=TextNormalizer.clean(extracted.state),
                country=TextNormalizer.clean(extracted.country),
                postal_code=TextNormalizer.clean(extracted.postal_code),
                raw=extracted.location_raw,
            )
        # Fall back to parsing the raw string
        return LocationNormalizer.normalize(extracted.location_raw)

    def _map_skills(self, raw_skills: list[str]) -> list[Skill]:
        """Normalize and deduplicate skills."""
        canonical_names = SkillNormalizer.normalize_list(raw_skills)
        seen: set[str] = set()
        skills: list[Skill] = []
        for name in canonical_names:
            if name not in seen:
                seen.add(name)
                aliases = SkillNormalizer.get_aliases(name)
                skills.append(Skill(canonical_name=name, aliases=aliases))
        return skills

    def _map_experience(self, raw: RawExperience) -> Experience:
        """Map a RawExperience to a canonical Experience."""
        start_date = DateNormalizer.parse(raw.start_date_raw)
        end_date = DateNormalizer.parse(raw.end_date_raw, is_end_date=True)
        is_current = raw.is_current or (
            raw.end_date_raw is not None
            and raw.end_date_raw.lower() in {"present", "current", "now", "ongoing"}
        )

        location = LocationNormalizer.normalize(raw.location_raw)

        return Experience(
            company=TextNormalizer.normalize_company(raw.company) or "Unknown",
            title=TextNormalizer.clean(raw.title) or "Unknown",
            location=location,
            start_date=start_date,
            end_date=end_date if not is_current else None,
            is_current=is_current,
            description=TextNormalizer.truncate(TextNormalizer.clean(raw.description), 2000),
            responsibilities=[
                TextNormalizer.clean(r) for r in raw.responsibilities if TextNormalizer.clean(r)
            ],
            technologies=SkillNormalizer.normalize_list(raw.technologies),
            achievements=[
                TextNormalizer.clean(a) for a in raw.achievements if TextNormalizer.clean(a)
            ],
        )

    def _map_education(self, raw: RawEducation) -> Education:
        """Map a RawEducation to a canonical Education."""
        degree = _parse_degree(raw.degree_raw)
        gpa = _parse_gpa(raw.gpa_raw)
        start_date = DateNormalizer.parse(raw.start_date_raw)
        end_date = DateNormalizer.parse(raw.end_date_raw, is_end_date=True)

        return Education(
            institution=TextNormalizer.normalize_company(raw.institution) or "Unknown",
            degree=degree,
            field_of_study=TextNormalizer.clean(raw.field_of_study),
            start_date=start_date,
            end_date=end_date,
            gpa=gpa,
            honors=[TextNormalizer.clean(h) for h in raw.honors if TextNormalizer.clean(h)],
        )

    def _map_project(self, raw: RawProject) -> Project:
        """Map a RawProject to a canonical Project."""
        url = UrlNormalizer.normalize(raw.url)
        repo_url = UrlNormalizer.normalize(raw.repository_url)
        start_date = DateNormalizer.parse(raw.start_date_raw)
        end_date = DateNormalizer.parse(raw.end_date_raw, is_end_date=True)

        return Project(
            name=TextNormalizer.clean(raw.name) or "Untitled",
            description=TextNormalizer.truncate(TextNormalizer.clean(raw.description), 1000),
            url=url,
            repository_url=repo_url,
            technologies=SkillNormalizer.normalize_list(raw.technologies),
            start_date=start_date,
            end_date=end_date,
            is_open_source=raw.is_open_source,
            stars=raw.stars,
            forks=raw.forks,
        )

    def _map_certification(self, raw: RawCertification) -> Certification:
        """Map a RawCertification to a canonical Certification."""
        return Certification(
            name=TextNormalizer.clean(raw.name) or "Unknown",
            issuing_organization=TextNormalizer.clean(raw.issuing_organization),
            issue_date=DateNormalizer.parse(raw.issue_date_raw),
            expiry_date=DateNormalizer.parse(raw.expiry_date_raw, is_end_date=True),
            credential_id=TextNormalizer.clean(raw.credential_id),
            credential_url=UrlNormalizer.normalize(raw.credential_url),
        )

    def _map_social_links(self, raw_links: list[dict]) -> list[SocialLink]:
        """Map raw social link dicts to SocialLink models."""
        links: list[SocialLink] = []
        seen_urls: set[str] = set()

        for raw in raw_links:
            if not isinstance(raw, dict):
                continue
            url = UrlNormalizer.normalize(raw.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            platform_str = (raw.get("platform") or "other").lower()
            try:
                platform = SocialPlatform(platform_str)
            except ValueError:
                platform = SocialPlatform.OTHER

            username = raw.get("username")
            links.append(SocialLink(platform=platform, url=url, username=username))

        return links

    def _map_languages(self, raw_languages: list[str]) -> list[Language]:
        """Map raw language strings to Language models."""
        seen: set[str] = set()
        result: list[Language] = []
        for lang in raw_languages:
            cleaned = TextNormalizer.clean(lang)
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                result.append(Language(name=cleaned.title()))
        return result
