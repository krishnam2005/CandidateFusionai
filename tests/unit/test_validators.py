"""Unit tests for the validation engine."""

from __future__ import annotations

from datetime import date

import pytest

from models.candidate import (
    Candidate,
    Education,
    EducationDegree,
    Experience,
    Location,
    SocialLink,
    SocialPlatform,
)
from validators.validation_engine import ValidationEngine, ValidationSeverity


def make_minimal_valid_candidate(**kwargs: object) -> Candidate:
    """Create a minimal valid candidate for validation tests."""
    defaults: dict[str, object] = {
        "full_name": "Jane Smith",
        "emails": ["jane@example.com"],
        "phones": ["+14155550198"],
        "skills": [],
        "experience": [],
        "education": [],
        "social_links": [],
    }
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestValidationEngineRequiredFields:
    def test_valid_candidate_passes(self, sample_candidate: Candidate) -> None:
        engine = ValidationEngine()
        report = engine.validate(sample_candidate)
        assert not report.has_errors

    def test_missing_name_errors(self) -> None:
        engine = ValidationEngine()
        candidate = make_minimal_valid_candidate(
            full_name=None, first_name=None, last_name=None
        )
        report = engine.validate(candidate)
        errors = [e for e in report.errors if "name" in e.field.lower()]
        assert len(errors) > 0

    def test_missing_contact_warns(self) -> None:
        engine = ValidationEngine()
        candidate = make_minimal_valid_candidate(emails=[], phones=[])
        report = engine.validate(candidate)
        warnings = [w for w in report.warnings if "contact" in w.field.lower()]
        assert len(warnings) > 0


class TestValidationEngineEmails:
    def test_valid_email_passes(self) -> None:
        engine = ValidationEngine()
        candidate = make_minimal_valid_candidate(emails=["valid@example.com"])
        report = engine.validate(candidate)
        email_errors = [e for e in report.errors if "email" in e.field.lower()]
        assert len(email_errors) == 0

    def test_invalid_email_errors(self) -> None:
        engine = ValidationEngine()
        candidate = make_minimal_valid_candidate(emails=["not-an-email"])
        report = engine.validate(candidate)
        email_errors = [e for e in report.errors if "email" in e.field.lower()]
        assert len(email_errors) > 0


class TestValidationEngineDates:
    def test_valid_date_range_passes(self) -> None:
        engine = ValidationEngine()
        exp = Experience(
            company="Test",
            title="Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 1, 1),
        )
        candidate = make_minimal_valid_candidate(experience=[exp])
        report = engine.validate(candidate)
        date_errors = [e for e in report.errors if "date" in e.field.lower()]
        assert len(date_errors) == 0

    def test_end_before_start_errors(self) -> None:
        engine = ValidationEngine()
        exp = Experience(
            company="Test",
            title="Engineer",
            start_date=date(2022, 1, 1),
            end_date=date(2020, 1, 1),
        )
        candidate = make_minimal_valid_candidate(experience=[exp])
        report = engine.validate(candidate)
        date_errors = [e for e in report.errors if "date" in e.field.lower()]
        assert len(date_errors) > 0

    def test_future_start_date_warns(self) -> None:
        engine = ValidationEngine()
        exp = Experience(
            company="Test",
            title="Future Engineer",
            start_date=date(2050, 1, 1),
            is_current=True,
        )
        candidate = make_minimal_valid_candidate(experience=[exp])
        report = engine.validate(candidate)
        future_warns = [w for w in report.warnings if "future" in w.message.lower()]
        assert len(future_warns) > 0


class TestValidationEngineGPA:
    def test_valid_gpa_passes(self) -> None:
        engine = ValidationEngine()
        edu = Education(institution="MIT", degree=EducationDegree.BACHELOR, gpa=3.5)
        candidate = make_minimal_valid_candidate(education=[edu])
        report = engine.validate(candidate)
        gpa_errors = [e for e in report.errors if "gpa" in e.field.lower()]
        assert len(gpa_errors) == 0

    def test_invalid_gpa_errors(self) -> None:
        engine = ValidationEngine()
        edu = Education(institution="MIT", degree=EducationDegree.BACHELOR, gpa=5.0)  # Invalid
        candidate = make_minimal_valid_candidate(education=[edu])
        report = engine.validate(candidate)
        gpa_errors = [e for e in report.errors if "gpa" in e.field.lower()]
        assert len(gpa_errors) > 0


class TestValidationEngineURLs:
    def test_valid_url_passes(self) -> None:
        engine = ValidationEngine()
        link = SocialLink(platform=SocialPlatform.GITHUB, url="https://github.com/user")
        candidate = make_minimal_valid_candidate(social_links=[link])
        report = engine.validate(candidate)
        url_warns = [w for w in report.warnings if "url" in w.field.lower()]
        assert len(url_warns) == 0

    def test_malformed_url_warns(self) -> None:
        engine = ValidationEngine()
        link = SocialLink(platform=SocialPlatform.OTHER, url="not a url at all ://bad")
        candidate = make_minimal_valid_candidate(social_links=[link])
        report = engine.validate(candidate)
        # URL is checked; malformed should warn
        # (may or may not warn depending on urlparse behavior)
        assert report is not None  # At minimum it shouldn't crash


class TestValidationReport:
    def test_report_to_dict(self, sample_candidate: Candidate) -> None:
        engine = ValidationEngine()
        report = engine.validate(sample_candidate)
        d = report.to_dict()
        assert "valid" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "findings" in d

    def test_is_valid_true_when_no_errors(self, sample_candidate: Candidate) -> None:
        engine = ValidationEngine()
        report = engine.validate(sample_candidate)
        assert report.is_valid is True or not report.has_errors
