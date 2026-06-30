"""Unit tests for extractor modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractors.ats_json import ATSJsonExtractor
from extractors.base import ExtractorError
from extractors.csv_extractor import CSVExtractor
from extractors.notes_extractor import NotesExtractor
from models.metadata import SourceType


class TestCSVExtractor:
    def test_extract_basic(self, sample_csv_path: Path) -> None:
        extractor = CSVExtractor()
        result = extractor.extract(sample_csv_path)

        assert result.source == SourceType.CSV
        assert result.first_name == "Jane"
        assert result.last_name == "Smith"
        assert "jane.smith@example.com" in result.emails

    def test_extract_skills_comma_separated(self, tmp_path: Path) -> None:
        csv_content = "first_name,last_name,email,skills\nJohn,Doe,john@example.com,\"Python,React,AWS\"\n"
        path = tmp_path / "test.csv"
        path.write_text(csv_content)

        extractor = CSVExtractor()
        result = extractor.extract(path)
        assert "Python" in result.skills_raw
        assert "React" in result.skills_raw

    def test_extract_missing_file_raises(self, tmp_path: Path) -> None:
        extractor = CSVExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(tmp_path / "nonexistent.csv")
        assert "not found" in str(exc_info.value)

    def test_extract_empty_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        path.write_text("first_name,last_name,email\n")  # Header only
        extractor = CSVExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(path)
        assert "empty" in str(exc_info.value).lower()

    def test_safe_extract_returns_none_on_error(self, tmp_path: Path) -> None:
        extractor = CSVExtractor()
        result = extractor.safe_extract(tmp_path / "nonexistent.csv")
        assert result is None

    def test_extract_semicolon_separated(self, tmp_path: Path) -> None:
        content = "first_name;last_name;email\nJane;Doe;jane@example.com\n"
        path = tmp_path / "semi.csv"
        path.write_text(content)
        extractor = CSVExtractor()
        result = extractor.extract(path)
        assert result.first_name == "Jane"

    def test_extract_yields_social_links(self, sample_csv_path: Path) -> None:
        extractor = CSVExtractor()
        result = extractor.extract(sample_csv_path)
        platforms = [l.get("platform") for l in result.social_links]
        assert "linkedin" in platforms


class TestATSJsonExtractor:
    def test_extract_basic(self, sample_ats_path: Path) -> None:
        extractor = ATSJsonExtractor()
        result = extractor.extract(sample_ats_path)

        assert result.source == SourceType.ATS
        assert result.full_name == "Jane Smith"
        assert "jane.smith@example.com" in result.emails
        assert len(result.experience) == 1
        assert len(result.education) == 1

    def test_extract_missing_file_raises(self, tmp_path: Path) -> None:
        extractor = ATSJsonExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(tmp_path / "nonexistent.json")
        assert "not found" in str(exc_info.value)

    def test_extract_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("this is not json {{{{")
        extractor = ATSJsonExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(path)
        assert "Invalid JSON" in str(exc_info.value)

    def test_extract_non_dict_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "array.json"
        path.write_text(json.dumps([{"name": "test"}]))
        extractor = ATSJsonExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(path)
        assert "JSON object" in str(exc_info.value)

    def test_extract_skills_list(self, tmp_path: Path) -> None:
        data = {"full_name": "Test User", "skills": ["Python", "Go", "Rust"]}
        path = tmp_path / "ats.json"
        path.write_bytes(json.dumps(data).encode())
        extractor = ATSJsonExtractor()
        result = extractor.extract(path)
        assert "Python" in result.skills_raw
        assert "Go" in result.skills_raw

    def test_extract_ats_id(self, sample_ats_path: Path) -> None:
        extractor = ATSJsonExtractor()
        result = extractor.extract(sample_ats_path)
        assert result.ats_candidate_id == "ATS-001"

    def test_extract_certifications(self, sample_ats_path: Path) -> None:
        extractor = ATSJsonExtractor()
        result = extractor.extract(sample_ats_path)
        assert len(result.certifications) == 1
        assert result.certifications[0].name == "AWS Certified Solutions Architect"

    def test_extract_languages(self, sample_ats_path: Path) -> None:
        extractor = ATSJsonExtractor()
        result = extractor.extract(sample_ats_path)
        assert "English" in result.languages
        assert "Spanish" in result.languages

    def test_extract_alternate_field_names(self, tmp_path: Path) -> None:
        """Test that extractor handles field name aliases."""
        data = {
            "name": "John Doe",  # alias for full_name
            "email_addresses": "john@example.com",  # alias for emails
            "phone_numbers": "+14155550100",  # alias for phones
        }
        path = tmp_path / "ats_alt.json"
        path.write_bytes(json.dumps(data).encode())
        extractor = ATSJsonExtractor()
        result = extractor.extract(path)
        assert result.full_name == "John Doe"
        assert "john@example.com" in result.emails


class TestNotesExtractor:
    def test_extract_basic(self, sample_notes_path: Path) -> None:
        extractor = NotesExtractor()
        result = extractor.extract(sample_notes_path)

        assert result.source == SourceType.NOTES
        assert result.full_name == "Jane Smith"
        assert "jane.smith@example.com" in result.emails

    def test_extract_skills_from_text(self, sample_notes_path: Path) -> None:
        extractor = NotesExtractor()
        result = extractor.extract(sample_notes_path)
        skills_lower = [s.lower() for s in result.skills_raw]
        # At least some skills should be detected
        assert len(result.skills_raw) > 0

    def test_extract_social_links(self, sample_notes_path: Path) -> None:
        extractor = NotesExtractor()
        result = extractor.extract(sample_notes_path)
        platforms = [l.get("platform") for l in result.social_links]
        assert "linkedin" in platforms
        assert "github" in platforms

    def test_extract_years_experience(self, tmp_path: Path) -> None:
        content = "Jane has 7 years of experience in Python development."
        path = tmp_path / "notes.txt"
        path.write_text(content)
        extractor = NotesExtractor()
        result = extractor.extract(path)
        assert result.years_of_experience == 7.0

    def test_extract_missing_file_raises(self, tmp_path: Path) -> None:
        extractor = NotesExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(tmp_path / "nonexistent.txt")
        assert "not found" in str(exc_info.value)

    def test_extract_empty_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.txt"
        path.write_text("   ")
        extractor = NotesExtractor()
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract(path)
        assert "empty" in str(exc_info.value).lower()

    def test_extract_location_from_label(self, tmp_path: Path) -> None:
        content = "Candidate: Test Person\nLocation: Seattle, WA\nSkills: Python"
        path = tmp_path / "notes.txt"
        path.write_text(content)
        extractor = NotesExtractor()
        result = extractor.extract(path)
        assert result.location_raw is not None
        assert "Seattle" in result.location_raw
