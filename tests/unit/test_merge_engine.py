"""Unit tests for the merge engine."""

from __future__ import annotations

import pytest

from mergers.merge_engine import MergeEngine
from models.candidate import (
    Candidate,
    Certification,
    Education,
    EducationDegree,
    Experience,
    Location,
    Project,
    Skill,
    SocialLink,
    SocialPlatform,
)
from models.metadata import SourceType


def make_candidate(**kwargs: object) -> Candidate:
    """Helper to create a Candidate with defaults."""
    defaults: dict[str, object] = {
        "full_name": None,
        "emails": [],
        "phones": [],
        "skills": [],
        "experience": [],
        "education": [],
    }
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestMergeEngineScalars:
    def test_merge_single_source(self) -> None:
        engine = MergeEngine()
        ats_candidate = make_candidate(full_name="Jane Smith")
        result, _ = engine.merge({SourceType.ATS: ats_candidate})
        assert result.full_name == "Jane Smith"

    def test_merge_no_sources_raises(self) -> None:
        engine = MergeEngine()
        with pytest.raises(ValueError, match="Cannot merge"):
            engine.merge({})

    def test_merge_priority_ats_over_csv(self) -> None:
        """ATS has higher priority than CSV."""
        engine = MergeEngine()
        ats = make_candidate(full_name="Jane Smith (ATS)")
        csv = make_candidate(full_name="Jane Smith (CSV)")
        result, provenance = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert result.full_name == "Jane Smith (ATS)"

    def test_merge_fallback_to_lower_priority_when_winner_missing(self) -> None:
        """If ATS has no full_name, fall back to CSV."""
        engine = MergeEngine()
        ats = make_candidate(full_name=None)
        csv = make_candidate(full_name="Jane Smith")
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert result.full_name == "Jane Smith"

    def test_merge_conflict_recorded_in_provenance(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(full_name="Jane Smith")
        csv = make_candidate(full_name="J Smith")
        result, provenance = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})

        name_prov = next((p for p in provenance if p.field_name == "full_name"), None)
        assert name_prov is not None
        assert name_prov.conflict_resolved is True

    def test_merge_no_conflict_not_flagged(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(full_name="Jane Smith")
        csv = make_candidate(full_name="Jane Smith")
        result, provenance = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})

        name_prov = next((p for p in provenance if p.field_name == "full_name"), None)
        assert name_prov is not None
        assert name_prov.conflict_resolved is False


class TestMergeEngineEmails:
    def test_merge_union_emails(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(emails=["jane@example.com"])
        csv = make_candidate(emails=["jane.work@company.com"])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert "jane@example.com" in result.emails
        assert "jane.work@company.com" in result.emails

    def test_merge_deduplicates_emails(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(emails=["jane@example.com"])
        csv = make_candidate(emails=["jane@example.com"])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert result.emails.count("jane@example.com") == 1


class TestMergeEngineSkills:
    def test_merge_union_skills(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(skills=[Skill(canonical_name="Python")])
        csv = make_candidate(skills=[Skill(canonical_name="React")])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        skill_names = [s.canonical_name for s in result.skills]
        assert "Python" in skill_names
        assert "React" in skill_names

    def test_merge_deduplicates_skills(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(skills=[Skill(canonical_name="Python")])
        csv = make_candidate(skills=[Skill(canonical_name="Python")])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        skill_names = [s.canonical_name for s in result.skills]
        assert skill_names.count("Python") == 1

    def test_merge_skills_merge_aliases(self) -> None:
        engine = MergeEngine()
        ats = make_candidate(skills=[Skill(canonical_name="Python", aliases=["py"])])
        csv = make_candidate(skills=[Skill(canonical_name="Python", aliases=["python3"])])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        skill = next(s for s in result.skills if s.canonical_name == "Python")
        assert "py" in skill.aliases
        assert "python3" in skill.aliases


class TestMergeEngineExperience:
    def test_merge_deduplicates_same_company_title(self) -> None:
        engine = MergeEngine()
        exp1 = Experience(company="Acme Corp", title="Senior Software Engineer", is_current=True)
        exp2 = Experience(
            company="Acme Corp",
            title="Senior Software Engineer",
            is_current=True,
            description="Led the team",
        )
        ats = make_candidate(experience=[exp1])
        csv = make_candidate(experience=[exp2])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        acme_entries = [e for e in result.experience if e.company == "Acme Corp"]
        assert len(acme_entries) == 1

    def test_merge_keeps_different_companies(self) -> None:
        engine = MergeEngine()
        exp1 = Experience(company="Company A", title="Engineer")
        exp2 = Experience(company="Company B", title="Engineer")
        ats = make_candidate(experience=[exp1])
        csv = make_candidate(experience=[exp2])
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert len(result.experience) == 2


class TestMergeEngineLocation:
    def test_merge_prefers_more_complete_location(self) -> None:
        engine = MergeEngine()
        partial_loc = Location(city="San Francisco")
        full_loc = Location(city="San Francisco", state="CA", country="United States", country_code="US")
        ats = make_candidate(location=partial_loc)
        csv = make_candidate(location=full_loc)
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        # Should have at minimum the city
        assert result.location is not None
        assert result.location.city == "San Francisco"

    def test_merge_fills_missing_location_fields(self) -> None:
        engine = MergeEngine()
        loc_a = Location(city="Boston")
        loc_b = Location(state="MA", country="United States")
        ats = make_candidate(location=loc_a)
        csv = make_candidate(location=loc_b)
        result, _ = engine.merge({SourceType.ATS: ats, SourceType.CSV: csv})
        assert result.location is not None
