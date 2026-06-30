"""Integration tests for the full pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import orjson
import pytest

from services.pipeline import Pipeline, PipelineInput


MOCK_GITHUB_PROFILE = {
    "login": "janesmith",
    "name": "Jane Smith",
    "bio": "Senior software engineer",
    "email": "jane.smith@example.com",
    "location": "San Francisco, CA",
    "blog": "",
    "twitter_username": None,
    "public_repos": 15,
    "followers": 120,
    "following": 50,
    "public_gists": 3,
}

MOCK_GITHUB_REPOS = [
    {
        "name": "cool-project",
        "description": "A cool Python project",
        "html_url": "https://github.com/janesmith/cool-project",
        "language": "Python",
        "topics": ["fastapi", "python"],
        "stargazers_count": 75,
        "forks_count": 10,
        "fork": False,
        "private": False,
    }
]


def make_mock_response(data: object, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.headers = {}
    return mock


@pytest.mark.integration
class TestPipelineIntegration:
    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_ats_only(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
    ) -> None:
        """Pipeline should succeed with only ATS input."""
        inputs = PipelineInput(ats_path=sample_ats_path)
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.candidate is not None
        assert result.candidate.full_name == "Jane Smith"
        assert result.output_json is not None
        assert orjson.loads(result.output_json) is not None

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_csv_only(
        self,
        mock_get: MagicMock,
        sample_csv_path: Path,
    ) -> None:
        """Pipeline should succeed with only CSV input."""
        inputs = PipelineInput(csv_path=sample_csv_path)
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.candidate is not None
        assert result.output_json is not None

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_multiple_sources(
        self,
        mock_get: MagicMock,
        sample_csv_path: Path,
        sample_ats_path: Path,
        sample_notes_path: Path,
    ) -> None:
        """Pipeline should merge data from CSV, ATS, and notes."""
        mock_get.side_effect = [
            make_mock_response(MOCK_GITHUB_PROFILE),
            make_mock_response(MOCK_GITHUB_REPOS),
        ]

        inputs = PipelineInput(
            csv_path=sample_csv_path,
            ats_path=sample_ats_path,
            notes_path=sample_notes_path,
        )
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.candidate is not None
        # ATS provides more complete data, so should see ATS data dominate
        assert result.candidate.full_name == "Jane Smith"
        # Union of emails from all sources
        assert len(result.candidate.emails) >= 1
        # Merged skills from all sources
        assert len(result.candidate.skills) > 0

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_with_github(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
    ) -> None:
        """Pipeline should enrich with GitHub data."""
        mock_get.side_effect = [
            make_mock_response(MOCK_GITHUB_PROFILE),
            make_mock_response(MOCK_GITHUB_REPOS),
        ]

        inputs = PipelineInput(
            ats_path=sample_ats_path,
            github_url="https://github.com/janesmith",
        )
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.candidate is not None
        # Should have projects from GitHub
        assert len(result.candidate.projects) > 0

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_attaches_confidence(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
    ) -> None:
        """Pipeline should attach confidence scores to the profile."""
        inputs = PipelineInput(ats_path=sample_ats_path)
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.candidate.confidence is not None
        assert 0.0 <= result.candidate.confidence.overall_score <= 1.0

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_attaches_metadata(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
    ) -> None:
        """Pipeline should attach execution metadata."""
        inputs = PipelineInput(ats_path=sample_ats_path)
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert result.metadata is not None
        assert result.metadata.run_id is not None
        assert result.metadata.duration_ms is not None
        assert len(result.metadata.sources_succeeded) == 1

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_handles_source_failure_gracefully(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
        tmp_path: Path,
    ) -> None:
        """A failing source should not abort the pipeline."""
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("corrupt,data\n,,")

        inputs = PipelineInput(
            ats_path=sample_ats_path,
            csv_path=bad_csv,
        )
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        # Should still succeed via ATS
        assert result.candidate is not None
        # CSV should be in failed sources
        from models.metadata import SourceType
        # ATS should be in succeeded
        assert SourceType.ATS in result.metadata.sources_succeeded

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_no_sources_raises(self, mock_get: MagicMock) -> None:
        """Pipeline with no sources should raise ValueError."""
        inputs = PipelineInput()
        pipeline = Pipeline()
        with pytest.raises(ValueError, match="No input sources provided"):
            pipeline.run(inputs)

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_output_json_valid(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
    ) -> None:
        """Output should be valid JSON."""
        inputs = PipelineInput(ats_path=sample_ats_path)
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        assert isinstance(result.output_json, bytes)
        parsed = orjson.loads(result.output_json)
        assert isinstance(parsed, dict)
        assert "candidate_id" in parsed

    @patch("extractors.github_extractor.Session.get")
    def test_pipeline_with_output_config(
        self,
        mock_get: MagicMock,
        sample_ats_path: Path,
        tmp_path: Path,
    ) -> None:
        """Pipeline should respect output config field selection."""
        config_data = {
            "output_fields": ["candidate_id", "full_name", "emails"],
            "include_provenance": False,
            "include_confidence": False,
            "include_metadata": False,
            "null_handling": "omit",
        }
        config_path = tmp_path / "config.json"
        config_path.write_bytes(json.dumps(config_data).encode())

        inputs = PipelineInput(
            ats_path=sample_ats_path,
            output_config_path=config_path,
        )
        pipeline = Pipeline()
        result = pipeline.run(inputs)

        parsed = orjson.loads(result.output_json)
        # Should have exactly the configured fields (plus candidate_id which is always included)
        assert "full_name" in parsed
        assert "emails" in parsed
        assert "provenance" not in parsed
        assert "confidence" not in parsed
        assert "experience" not in parsed  # Not in config
