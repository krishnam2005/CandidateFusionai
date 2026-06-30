"""
mergers.merge_engine — Deterministic multi-source candidate data merge engine.

Merge Strategy
==============

Source priority (highest → lowest):
  ATS (0.95) > CSV (0.92) > Resume (0.90) > GitHub (0.80) > Notes (0.70)

Scalar field merge rules:
  - Use the highest-priority source that has a non-None value.
  - If a lower-priority source disagrees, record a conflict in provenance.

Array field merge rules:
  - Skills: union across all sources, deduplicated by canonical_name.
  - Experience: merged by (company, title) similarity (RapidFuzz).
    Duplicates are merged, keeping the richer version.
  - Education: merged by institution similarity.
  - Projects: merged by name similarity.
  - Certifications: merged by name.
  - Social links: union by URL, deduplication.
  - Emails: union, deduplicated (EmailNormalizer ensures canonical form).
  - Phones: union, deduplicated.

Conflict resolution is documented per-field in the MergeResult.

Design principles:
  - Deterministic: same inputs always produce the same output.
  - No side effects: produces a new Candidate, doesn't mutate inputs.
  - Every decision is logged and stored in provenance records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rapidfuzz import fuzz

from models.candidate import (
    Candidate,
    Certification,
    Education,
    Experience,
    Language,
    Location,
    Project,
    Skill,
    SocialLink,
)
from models.metadata import PipelineMetadata, SourceType
from models.provenance import DIRECT_FIELD, FUZZY_MATCH, FieldProvenance, ProvenanceRecord
from normalizers.location_normalizer import LocationNormalizer
from normalizers.text_normalizer import TextNormalizer
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)

# Source priority order (index = priority; 0 = highest)
SOURCE_PRIORITY: list[SourceType] = [
    SourceType.ATS,
    SourceType.CSV,
    SourceType.RESUME,
    SourceType.GITHUB,
    SourceType.NOTES,
]

# Source base confidence weights
SOURCE_WEIGHTS: dict[SourceType, float] = {
    SourceType.ATS: 0.95,
    SourceType.CSV: 0.92,
    SourceType.RESUME: 0.90,
    SourceType.GITHUB: 0.80,
    SourceType.NOTES: 0.70,
    SourceType.UNKNOWN: 0.50,
}

# Similarity threshold for array deduplication (0-100 RapidFuzz scale)
_COMPANY_SIMILARITY_THRESHOLD = 80
_INSTITUTION_SIMILARITY_THRESHOLD = 80
_PROJECT_SIMILARITY_THRESHOLD = 85
_CERT_SIMILARITY_THRESHOLD = 85


def _priority_of(source: SourceType) -> int:
    """Return priority index (lower = higher priority) for a source."""
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


class MergeEngine:
    """
    Merges multiple canonical Candidate objects (one per source) into a
    single unified Candidate profile.

    Usage::

        engine = MergeEngine()
        merged, provenance_records = engine.merge(
            candidates_by_source={
                SourceType.ATS: ats_candidate,
                SourceType.CSV: csv_candidate,
            }
        )
    """

    def merge(
        self,
        candidates_by_source: dict[SourceType, Candidate],
    ) -> tuple[Candidate, list[FieldProvenance]]:
        """
        Merge candidates from multiple sources into one canonical profile.

        Parameters
        ----------
        candidates_by_source:
            Mapping of SourceType → Candidate.  All candidates are assumed
            to represent the same person (entity resolution is upstream).

        Returns
        -------
        (merged_candidate, provenance_records):
            The merged Candidate and a list of FieldProvenance records
            documenting every merge decision.
        """
        if not candidates_by_source:
            raise ValueError("Cannot merge: no candidates provided")

        # Sort by priority so we always process in deterministic order
        ordered: list[tuple[SourceType, Candidate]] = sorted(
            candidates_by_source.items(),
            key=lambda kv: _priority_of(kv[0]),
        )

        provenance_records: list[FieldProvenance] = []

        with timed("merge_engine", source_count=len(ordered)):
            merged = self._merge_all(ordered, provenance_records)

        log.info(
            "merge_complete",
            sources=[s.value for s, _ in ordered],
            provenance_fields=len(provenance_records),
            skills=len(merged.skills),
            experience=len(merged.experience),
        )

        return merged, provenance_records

    def _merge_all(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> Candidate:
        """Perform full merge of all fields."""

        def pick_scalar(
            field_name: str,
            getter: Any,
        ) -> tuple[Any, list[FieldProvenance]]:
            """Pick the best scalar value using source priority."""
            return self._pick_scalar(field_name, ordered, getter, provenance_records)

        # ── Scalar fields ─────────────────────────────────────────────────
        full_name = pick_scalar("full_name", lambda c: c.full_name)
        first_name = pick_scalar("first_name", lambda c: c.first_name)
        last_name = pick_scalar("last_name", lambda c: c.last_name)
        summary = pick_scalar("summary", lambda c: c.summary)
        headline = pick_scalar("headline", lambda c: c.headline)
        years_exp = pick_scalar("years_of_experience", lambda c: c.years_of_experience)

        # ── Location: prefer most complete ────────────────────────────────
        location = self._merge_location(ordered, provenance_records)

        # ── Array fields ──────────────────────────────────────────────────
        emails = self._merge_emails(ordered, provenance_records)
        phones = self._merge_phones(ordered, provenance_records)
        skills = self._merge_skills(ordered, provenance_records)
        experience = self._merge_experience(ordered, provenance_records)
        education = self._merge_education(ordered, provenance_records)
        projects = self._merge_projects(ordered, provenance_records)
        certifications = self._merge_certifications(ordered, provenance_records)
        social_links = self._merge_social_links(ordered, provenance_records)
        languages = self._merge_languages(ordered, provenance_records)

        return Candidate(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            emails=emails,
            phones=phones,
            location=location,
            summary=summary,
            headline=headline,
            years_of_experience=years_exp,
            skills=skills,
            experience=experience,
            education=education,
            projects=projects,
            certifications=certifications,
            social_links=social_links,
            languages=languages,
        )

    def _pick_scalar(
        self,
        field_name: str,
        ordered: list[tuple[SourceType, Candidate]],
        getter: Any,
        provenance_records: list[FieldProvenance],
    ) -> Any:
        """
        Pick a scalar field value using source priority.

        Records provenance and flags conflicts.
        """
        candidates_with_value: list[tuple[SourceType, Any]] = [
            (source, getter(candidate))
            for source, candidate in ordered
            if getter(candidate) is not None
        ]

        if not candidates_with_value:
            return None

        winner_source, winner_value = candidates_with_value[0]
        all_values = [v for _, v in candidates_with_value]
        conflict = len(set(str(v).lower().strip() for v in all_values)) > 1

        winner_prov = ProvenanceRecord(
            source=winner_source,
            extraction_method=DIRECT_FIELD,
            value=winner_value,
            confidence=SOURCE_WEIGHTS.get(winner_source, 0.5),
            extracted_at=datetime.utcnow(),
        )

        all_prov = [
            ProvenanceRecord(
                source=src,
                extraction_method=DIRECT_FIELD,
                value=val,
                confidence=SOURCE_WEIGHTS.get(src, 0.5),
                extracted_at=datetime.utcnow(),
            )
            for src, val in candidates_with_value
        ]

        resolution_reason = (
            f"Selected value from highest-priority source '{winner_source}' "
            + (f"(conflict: {len(candidates_with_value)} sources disagreed)" if conflict else "(no conflict)")
        )

        provenance_records.append(
            FieldProvenance(
                field_name=field_name,
                selected=winner_prov,
                candidates=all_prov,
                conflict_resolved=conflict,
                resolution_reason=resolution_reason,
            )
        )

        if conflict:
            log.debug(
                "merge_conflict_resolved",
                field=field_name,
                winner_source=winner_source,
                winner_value=str(winner_value)[:100],
                other_values=[str(v)[:50] for _, v in candidates_with_value[1:]],
            )

        return winner_value

    def _merge_location(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> Location | None:
        """Merge locations by preferring the most complete one."""
        locations = [(src, c.location) for src, c in ordered if c.location]
        if not locations:
            return None

        # Score each location by completeness (number of non-None fields)
        def completeness(loc: Location) -> int:
            return sum(
                1
                for f in [loc.city, loc.state, loc.country, loc.country_code, loc.postal_code]
                if f
            )

        # Sort by priority first, then completeness as tiebreaker
        locations_scored = sorted(
            locations,
            key=lambda kv: (_priority_of(kv[0]), -completeness(kv[1])),
        )

        best_source, best_loc = locations_scored[0]

        # Merge remaining locations to fill missing fields
        merged_loc = best_loc
        for _, loc in locations_scored[1:]:
            merged_loc = LocationNormalizer.merge(merged_loc, loc)

        provenance_records.append(
            FieldProvenance(
                field_name="location",
                selected=ProvenanceRecord(
                    source=best_source,
                    extraction_method=DIRECT_FIELD,
                    value=merged_loc.model_dump() if merged_loc else None,
                    confidence=SOURCE_WEIGHTS.get(best_source, 0.5),
                ),
                candidates=[
                    ProvenanceRecord(
                        source=src,
                        extraction_method=DIRECT_FIELD,
                        value=loc.model_dump(),
                        confidence=SOURCE_WEIGHTS.get(src, 0.5),
                    )
                    for src, loc in locations_scored
                ],
                resolution_reason="Merged all location sources, filling missing fields",
            )
        )

        return merged_loc

    def _merge_emails(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[str]:
        """Union of all unique emails, ordered by source priority."""
        seen: set[str] = set()
        result: list[str] = []
        for source, candidate in ordered:
            for email in candidate.emails:
                if email not in seen:
                    seen.add(email)
                    result.append(email)
        self._record_array_provenance("emails", result, provenance_records)
        return result

    def _merge_phones(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[str]:
        """Union of all unique phones."""
        seen: set[str] = set()
        result: list[str] = []
        for _, candidate in ordered:
            for phone in candidate.phones:
                if phone not in seen:
                    seen.add(phone)
                    result.append(phone)
        self._record_array_provenance("phones", result, provenance_records)
        return result

    def _merge_skills(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Skill]:
        """
        Union of skills from all sources, deduplicated by canonical_name.

        When two sources provide the same canonical skill, the one from the
        higher-priority source is kept.  Aliases are merged across sources.
        """
        skill_map: dict[str, Skill] = {}
        alias_map: dict[str, set[str]] = {}

        for _, candidate in ordered:
            for skill in candidate.skills:
                name = skill.canonical_name
                if name not in skill_map:
                    skill_map[name] = skill
                    alias_map[name] = set(skill.aliases)
                else:
                    # Merge aliases from all sources
                    alias_map[name].update(skill.aliases)
                    # Keep higher confidence fields
                    existing = skill_map[name]
                    if skill.level.value != "unknown" and existing.level.value == "unknown":
                        skill_map[name] = skill.model_copy(update={"aliases": list(alias_map[name])})

        # Update aliases
        result = [
            s.model_copy(update={"aliases": list(alias_map[s.canonical_name])})
            for s in skill_map.values()
        ]

        self._record_array_provenance("skills", [s.canonical_name for s in result], provenance_records)
        return result

    def _merge_experience(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Experience]:
        """
        Merge experience entries by deduplicating similar company+title combinations.

        Uses RapidFuzz token_sort_ratio to find near-duplicates.
        When duplicates are found, the higher-priority source version is kept,
        supplemented with any unique data from the lower-priority version.
        """
        all_experiences: list[tuple[SourceType, Experience]] = []
        for source, candidate in ordered:
            for exp in candidate.experience:
                all_experiences.append((source, exp))

        merged: list[tuple[SourceType, Experience]] = []
        used: set[int] = set()

        for i, (src_a, exp_a) in enumerate(all_experiences):
            if i in used:
                continue
            group = [(src_a, exp_a)]
            for j, (src_b, exp_b) in enumerate(all_experiences[i + 1:], start=i + 1):
                if j in used:
                    continue
                company_sim = fuzz.token_sort_ratio(
                    (exp_a.company or "").lower(),
                    (exp_b.company or "").lower(),
                )
                title_sim = fuzz.token_sort_ratio(
                    (exp_a.title or "").lower(),
                    (exp_b.title or "").lower(),
                )
                if company_sim >= _COMPANY_SIMILARITY_THRESHOLD and title_sim >= 60:
                    group.append((src_b, exp_b))
                    used.add(j)

            # Use highest-priority version, fill gaps from others
            best_src, best_exp = group[0]
            for _, other_exp in group[1:]:
                best_exp = self._enrich_experience(best_exp, other_exp)

            merged.append((best_src, best_exp))
            used.add(i)

        result = [exp for _, exp in merged]
        self._record_array_provenance(
            "experience",
            [f"{e.company} | {e.title}" for e in result],
            provenance_records,
        )
        return result

    def _merge_education(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Education]:
        """Merge education entries, deduplicating by institution similarity."""
        all_edu: list[tuple[SourceType, Education]] = []
        for source, candidate in ordered:
            for edu in candidate.education:
                all_edu.append((source, edu))

        merged: list[Education] = []
        used: set[int] = set()

        for i, (_, edu_a) in enumerate(all_edu):
            if i in used:
                continue
            group = [edu_a]
            for j, (_, edu_b) in enumerate(all_edu[i + 1:], start=i + 1):
                if j in used:
                    continue
                sim = fuzz.token_sort_ratio(
                    (edu_a.institution or "").lower(),
                    (edu_b.institution or "").lower(),
                )
                if sim >= _INSTITUTION_SIMILARITY_THRESHOLD:
                    group.append(edu_b)
                    used.add(j)

            best = group[0]
            for other in group[1:]:
                best = self._enrich_education(best, other)

            merged.append(best)
            used.add(i)

        self._record_array_provenance(
            "education",
            [e.institution for e in merged],
            provenance_records,
        )
        return merged

    def _merge_projects(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Project]:
        """Merge projects by name similarity."""
        all_projects: list[Project] = []
        for _, candidate in ordered:
            all_projects.extend(candidate.projects)

        merged: list[Project] = []
        used: set[int] = set()

        for i, proj_a in enumerate(all_projects):
            if i in used:
                continue
            group = [proj_a]
            for j, proj_b in enumerate(all_projects[i + 1:], start=i + 1):
                if j in used:
                    continue
                sim = fuzz.token_sort_ratio(
                    (proj_a.name or "").lower(),
                    (proj_b.name or "").lower(),
                )
                if sim >= _PROJECT_SIMILARITY_THRESHOLD:
                    group.append(proj_b)
                    used.add(j)

            best = group[0]
            for other in group[1:]:
                best = self._enrich_project(best, other)

            merged.append(best)
            used.add(i)

        self._record_array_provenance(
            "projects",
            [p.name for p in merged],
            provenance_records,
        )
        return merged

    def _merge_certifications(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Certification]:
        """Merge certifications by name similarity."""
        all_certs: list[Certification] = []
        for _, candidate in ordered:
            all_certs.extend(candidate.certifications)

        merged: list[Certification] = []
        used: set[int] = set()

        for i, cert_a in enumerate(all_certs):
            if i in used:
                continue
            group = [cert_a]
            for j, cert_b in enumerate(all_certs[i + 1:], start=i + 1):
                if j in used:
                    continue
                sim = fuzz.token_sort_ratio(
                    (cert_a.name or "").lower(),
                    (cert_b.name or "").lower(),
                )
                if sim >= _CERT_SIMILARITY_THRESHOLD:
                    group.append(cert_b)
                    used.add(j)

            merged.append(group[0])
            used.add(i)

        self._record_array_provenance(
            "certifications",
            [c.name for c in merged],
            provenance_records,
        )
        return merged

    def _merge_social_links(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[SocialLink]:
        """Union of social links, deduplicated by normalized URL."""
        seen_urls: set[str] = set()
        result: list[SocialLink] = []
        for _, candidate in ordered:
            for link in candidate.social_links:
                if link.url not in seen_urls:
                    seen_urls.add(link.url)
                    result.append(link)
        self._record_array_provenance(
            "social_links",
            [f"{l.platform}:{l.url}" for l in result],
            provenance_records,
        )
        return result

    def _merge_languages(
        self,
        ordered: list[tuple[SourceType, Candidate]],
        provenance_records: list[FieldProvenance],
    ) -> list[Language]:
        """Union of languages, deduplicated by name."""
        seen: set[str] = set()
        result: list[Language] = []
        for _, candidate in ordered:
            for lang in candidate.languages:
                if lang.name.lower() not in seen:
                    seen.add(lang.name.lower())
                    result.append(lang)
        return result

    # ── Enrichment helpers ────────────────────────────────────────────────

    def _enrich_experience(self, base: Experience, supplement: Experience) -> Experience:
        """Fill missing fields in base from supplement."""
        return base.model_copy(update={
            "description": base.description or supplement.description,
            "start_date": base.start_date or supplement.start_date,
            "end_date": base.end_date or supplement.end_date,
            "location": base.location or supplement.location,
            "responsibilities": base.responsibilities or supplement.responsibilities,
            "technologies": list(set(base.technologies + supplement.technologies)),
            "achievements": base.achievements or supplement.achievements,
        })

    def _enrich_education(self, base: Education, supplement: Education) -> Education:
        """Fill missing fields in base from supplement."""
        return base.model_copy(update={
            "degree": base.degree if base.degree.value != "unknown" else supplement.degree,
            "field_of_study": base.field_of_study or supplement.field_of_study,
            "start_date": base.start_date or supplement.start_date,
            "end_date": base.end_date or supplement.end_date,
            "gpa": base.gpa or supplement.gpa,
            "honors": base.honors or supplement.honors,
        })

    def _enrich_project(self, base: Project, supplement: Project) -> Project:
        """Fill missing fields in base from supplement."""
        return base.model_copy(update={
            "description": base.description or supplement.description,
            "url": base.url or supplement.url,
            "repository_url": base.repository_url or supplement.repository_url,
            "technologies": list(set(base.technologies + supplement.technologies)),
            "stars": base.stars or supplement.stars,
            "forks": base.forks or supplement.forks,
        })

    def _record_array_provenance(
        self,
        field_name: str,
        values: list[Any],
        provenance_records: list[FieldProvenance],
    ) -> None:
        """Record a simple provenance entry for an array field."""
        provenance_records.append(
            FieldProvenance(
                field_name=field_name,
                selected=ProvenanceRecord(
                    source=SourceType.UNKNOWN,
                    extraction_method=DIRECT_FIELD,
                    value=values,
                    confidence=1.0,
                    notes="Merged from all available sources",
                ),
                resolution_reason="Union merge across all sources with deduplication",
            )
        )
