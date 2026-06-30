"""Shared test fixtures for CandidateFusion AI tests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

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
from models.extracted import ExtractedCandidate, RawEducation, RawExperience
from models.metadata import SourceType


# ── File fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_csv_path(tmp_path: Path) -> Path:
    """Create a sample CSV file in a temp directory."""
    content = textwrap.dedent("""\
        first_name,last_name,email,phone,location,current_title,current_company,skills,years_experience,linkedin_url
        Jane,Smith,jane.smith@example.com,+14155550198,"San Francisco, CA",Senior Software Engineer,Acme Corp,"Python,Django,React,PostgreSQL",7.5,https://linkedin.com/in/janesmith
    """)
    path = tmp_path / "recruiter.csv"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def sample_ats_path(tmp_path: Path) -> Path:
    """Create a sample ATS JSON file in a temp directory."""
    data = {
        "id": "ATS-001",
        "full_name": "Jane Smith",
        "emails": ["jane.smith@example.com"],
        "phones": ["+14155550198"],
        "location": "San Francisco, CA",
        "summary": "Senior software engineer with 7 years of experience.",
        "years_of_experience": 7.0,
        "skills": ["Python", "Django", "React", "PostgreSQL", "AWS"],
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Senior Software Engineer",
                "start_date": "2021-03",
                "is_current": True,
                "responsibilities": ["Led data platform team"],
                "technologies": ["Python", "FastAPI", "Kafka"],
            }
        ],
        "education": [
            {
                "institution": "University of California, Berkeley",
                "degree": "Bachelor of Science",
                "field_of_study": "Computer Science",
                "end_date": "2016-05",
                "gpa": "3.8",
            }
        ],
        "certifications": [
            {
                "name": "AWS Certified Solutions Architect",
                "issuing_organization": "Amazon Web Services",
                "issue_date": "2022-11",
            }
        ],
        "social_links": [
            {"platform": "linkedin", "url": "https://linkedin.com/in/janesmith"},
            {"platform": "github", "url": "https://github.com/janesmith"},
        ],
        "languages": ["English", "Spanish"],
    }
    path = tmp_path / "ats.json"
    path.write_bytes(json.dumps(data).encode())
    return path


@pytest.fixture()
def sample_notes_path(tmp_path: Path) -> Path:
    """Create a sample recruiter notes file."""
    content = textwrap.dedent("""\
        Candidate: Jane Smith
        Email: jane.smith@example.com
        Phone: (415) 555-0198
        Location: San Francisco, CA

        7+ years of experience in Python and backend systems.

        Skills: Python, Django, React, FastAPI, PostgreSQL, Redis, Docker, AWS, Kubernetes

        LinkedIn: linkedin.com/in/janesmith
        GitHub: github.com/janesmith

        Strong hire recommendation.
    """)
    path = tmp_path / "notes.txt"
    path.write_text(content, encoding="utf-8")
    return path


# ── Model fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_extracted_candidate() -> ExtractedCandidate:
    """Sample ExtractedCandidate for unit tests."""
    return ExtractedCandidate(
        source=SourceType.ATS,
        raw_path="inputs/ats.json",
        full_name="Jane Smith",
        first_name="Jane",
        last_name="Smith",
        emails=["jane.smith@example.com"],
        phones=["+14155550198"],
        location_raw="San Francisco, CA",
        city="San Francisco",
        state="CA",
        country="United States",
        summary="Senior software engineer with 7 years experience.",
        years_of_experience=7.0,
        skills_raw=["Python", "Django", "React", "PostgreSQL"],
        experience=[
            RawExperience(
                company="Acme Corp",
                title="Senior Software Engineer",
                start_date_raw="2021-03",
                is_current=True,
            )
        ],
        education=[
            RawEducation(
                institution="UC Berkeley",
                degree_raw="Bachelor of Science",
                field_of_study="Computer Science",
                end_date_raw="2016-05",
                gpa_raw="3.8",
            )
        ],
        social_links=[
            {"platform": "linkedin", "url": "https://linkedin.com/in/janesmith"},
            {"platform": "github", "url": "https://github.com/janesmith"},
        ],
        languages=["English", "Spanish"],
    )


@pytest.fixture()
def sample_candidate() -> Candidate:
    """Sample canonical Candidate for unit tests."""
    return Candidate(
        full_name="Jane Smith",
        first_name="Jane",
        last_name="Smith",
        emails=["jane.smith@example.com"],
        phones=["+14155550198"],
        location=Location(
            city="San Francisco",
            state="CA",
            country="United States",
            country_code="US",
        ),
        summary="Senior software engineer with 7 years experience.",
        years_of_experience=7.0,
        skills=[
            Skill(canonical_name="Python"),
            Skill(canonical_name="Django"),
            Skill(canonical_name="React"),
            Skill(canonical_name="PostgreSQL"),
        ],
        experience=[
            Experience(
                company="Acme Corp",
                title="Senior Software Engineer",
                is_current=True,
                technologies=["Python", "FastAPI"],
            )
        ],
        education=[
            Education(
                institution="University of California, Berkeley",
                degree=EducationDegree.BACHELOR,
                field_of_study="Computer Science",
                gpa=3.8,
            )
        ],
        social_links=[
            SocialLink(platform=SocialPlatform.LINKEDIN, url="https://linkedin.com/in/janesmith"),
            SocialLink(platform=SocialPlatform.GITHUB, url="https://github.com/janesmith"),
        ],
        certifications=[
            Certification(
                name="AWS Certified Solutions Architect",
                issuing_organization="Amazon Web Services",
            )
        ],
        languages=[Language(name="English"), Language(name="Spanish")],
    )
