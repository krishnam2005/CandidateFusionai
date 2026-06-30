"""Unit tests for the output projector."""

from __future__ import annotations

import json
from pathlib import Path

import orjson
import pytest

from models.candidate import Candidate, Skill
from projection.projector import OutputConfig, Projector


class TestOutputConfig:
    def test_default_config(self) -> None:
        config = OutputConfig.default()
        assert "full_name" in config.output_fields
        assert config.include_confidence is True
        assert config.include_provenance is True
        assert config.null_handling == "omit"

    def test_from_file_loads_correctly(self, tmp_path: Path) -> None:
        data = {
            "output_fields": ["candidate_id", "full_name", "emails"],
            "include_provenance": False,
            "include_confidence": True,
            "include_metadata": False,
            "null_handling": "omit",
        }
        path = tmp_path / "config.json"
        path.write_bytes(json.dumps(data).encode())

        config = OutputConfig.from_file(path)
        assert config.output_fields == ["candidate_id", "full_name", "emails"]
        assert config.include_provenance is False
        assert config.include_confidence is True

    def test_from_file_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_config.json"
        path.write_text("{ this is not valid json }")
        with pytest.raises(ValueError, match="Invalid JSON"):
            OutputConfig.from_file(path)

    def test_from_file_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Cannot read"):
            OutputConfig.from_file(tmp_path / "nonexistent.json")


class TestProjector:
    def test_project_returns_dict(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        result = projector.project(sample_candidate, [])
        assert isinstance(result, dict)

    def test_project_includes_candidate_id(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        result = projector.project(sample_candidate, [])
        assert "candidate_id" in result

    def test_project_field_selection(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        config = OutputConfig(
            output_fields=["candidate_id", "full_name", "emails"],
            include_provenance=False,
            include_confidence=False,
            include_metadata=False,
        )
        result = projector.project(sample_candidate, [], config)
        assert "full_name" in result
        assert "emails" in result
        assert "skills" not in result
        assert "experience" not in result

    def test_project_null_handling_omit(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        config = OutputConfig(null_handling="omit", include_provenance=False, include_confidence=False, include_metadata=False)
        result = projector.project(sample_candidate, [], config)
        # Null values should not be in the output
        for v in result.values():
            assert v is not None

    def test_project_null_handling_null(self) -> None:
        projector = Projector()
        candidate = Candidate(full_name=None, emails=[])
        config = OutputConfig(
            output_fields=["candidate_id", "full_name"],
            null_handling="null",
            include_provenance=False,
            include_confidence=False,
            include_metadata=False,
        )
        result = projector.project(candidate, [], config)
        assert "full_name" in result
        assert result["full_name"] is None

    def test_to_json_returns_bytes(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        result = projector.to_json(sample_candidate, [])
        assert isinstance(result, bytes)

    def test_to_json_is_valid_json(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        result = projector.to_json(sample_candidate, [])
        parsed = orjson.loads(result)
        assert isinstance(parsed, dict)

    def test_project_skills_serialized_correctly(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        config = OutputConfig(
            output_fields=["candidate_id", "skills"],
            include_provenance=False,
            include_confidence=False,
            include_metadata=False,
            null_handling="null",
        )
        result = projector.project(sample_candidate, [], config)
        assert "skills" in result
        assert isinstance(result["skills"], list)
        if result["skills"]:
            first_skill = result["skills"][0]
            assert "name" in first_skill

    def test_project_experience_serialized_correctly(self, sample_candidate: Candidate) -> None:
        projector = Projector()
        config = OutputConfig(
            output_fields=["candidate_id", "experience"],
            include_provenance=False,
            include_confidence=False,
            include_metadata=False,
            null_handling="null",
        )
        result = projector.project(sample_candidate, [], config)
        assert "experience" in result
        if result["experience"]:
            exp = result["experience"][0]
            assert "company" in exp
            assert "title" in exp
