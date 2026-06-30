"""Unit tests for the canonical mapper."""

from __future__ import annotations

import pytest

from models.extracted import ExtractedCandidate, RawEducation, RawExperience, RawProject
from models.metadata import SourceType
from services.canonical_mapper import CanonicalMapper


class TestCanonicalMapper:
    def test_map_basic_extracted(self, sample_extracted_candidate: ExtractedCandidate) -> None:
        mapper = CanonicalMapper()
        candidate = mapper.map(sample_extracted_candidate)

        assert candidate.full_name == "Jane Smith"
        assert candidate.first_name == "Jane"
        assert candidate.last_name == "Smith"
        assert "jane.smith@example.com" in candidate.emails
        assert "+14155550198" in candidate.phones

    def test_map_normalizes_emails(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.CSV,
            emails=["TEST@EXAMPLE.COM", "TEST@EXAMPLE.COM"],  # Duplicate
        )
        candidate = mapper.map(extracted)
        assert candidate.emails.count("test@example.com") == 1

    def test_map_normalizes_phones(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.CSV,
            phones=["(415) 555-0198"],
        )
        candidate = mapper.map(extracted)
        assert "+14155550198" in candidate.phones

    def test_map_normalizes_skills(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            skills_raw=["python3", "reactjs", "k8s"],
        )
        candidate = mapper.map(extracted)
        skill_names = candidate.skill_names()
        assert "Python" in skill_names
        assert "React" in skill_names
        assert "Kubernetes" in skill_names

    def test_map_infers_name_parts_from_full_name(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            full_name="Alice Johnson",
        )
        candidate = mapper.map(extracted)
        assert candidate.first_name == "Alice"
        assert candidate.last_name == "Johnson"

    def test_map_infers_full_name_from_parts(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.CSV,
            first_name="Bob",
            last_name="Williams",
        )
        candidate = mapper.map(extracted)
        assert candidate.full_name == "Bob Williams"

    def test_map_location_from_structured_fields(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            city="New York",
            state="NY",
            country="United States",
        )
        candidate = mapper.map(extracted)
        assert candidate.location is not None
        assert candidate.location.city == "New York"

    def test_map_location_from_raw_string(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.CSV,
            location_raw="Seattle, WA",
        )
        candidate = mapper.map(extracted)
        assert candidate.location is not None

    def test_map_experience_parses_dates(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            experience=[
                RawExperience(
                    company="Test Corp",
                    title="Engineer",
                    start_date_raw="Jan 2020",
                    end_date_raw="Present",
                    is_current=True,
                )
            ],
        )
        candidate = mapper.map(extracted)
        assert len(candidate.experience) == 1
        exp = candidate.experience[0]
        assert exp.is_current is True
        assert exp.start_date is not None

    def test_map_education_parses_degree(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            education=[
                RawEducation(
                    institution="MIT",
                    degree_raw="Master of Science in Computer Science",
                    gpa_raw="3.9",
                )
            ],
        )
        candidate = mapper.map(extracted)
        assert len(candidate.education) == 1
        edu = candidate.education[0]
        assert edu.degree.value == "master"
        assert edu.gpa == 3.9

    def test_map_project_normalizes_technologies(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.GITHUB,
            projects=[
                RawProject(
                    name="My Project",
                    technologies=["python3", "reactjs"],
                )
            ],
        )
        candidate = mapper.map(extracted)
        assert len(candidate.projects) == 1
        techs = candidate.projects[0].technologies
        assert "Python" in techs
        assert "React" in techs

    def test_map_deduplicates_skills(self) -> None:
        mapper = CanonicalMapper()
        extracted = ExtractedCandidate(
            source=SourceType.ATS,
            skills_raw=["Python", "python3", "python"],
        )
        candidate = mapper.map(extracted)
        assert candidate.skill_names().count("Python") == 1
