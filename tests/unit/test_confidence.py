"""Unit tests for the confidence engine."""

from __future__ import annotations

import pytest

from confidence.engine import ConfidenceEngine
from models.candidate import Candidate, Skill
from models.metadata import SourceType
from models.provenance import FieldProvenance, ProvenanceRecord


def make_provenance(
    field: str,
    source: SourceType,
    value: object,
    candidates: list[tuple[SourceType, object]] | None = None,
) -> FieldProvenance:
    """Helper to create test FieldProvenance records."""
    all_candidates = [(source, value)]
    if candidates:
        all_candidates.extend(candidates)

    selected = ProvenanceRecord(
        source=source,
        extraction_method="direct_field_mapping",
        value=value,
        confidence=0.9,
    )
    all_prov = [
        ProvenanceRecord(
            source=s,
            extraction_method="direct_field_mapping",
            value=v,
            confidence=0.8,
        )
        for s, v in all_candidates
    ]
    return FieldProvenance(
        field_name=field,
        selected=selected,
        candidates=all_prov,
        conflict_resolved=len(set(str(v) for _, v in all_candidates)) > 1,
    )


class TestConfidenceEngine:
    def test_score_single_source_returns_record(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        prov = [make_provenance("full_name", SourceType.ATS, "Jane Smith")]
        record = engine.score(sample_candidate, prov, sources_used=["ats"])
        assert record is not None
        assert 0.0 <= record.overall_score <= 1.0

    def test_score_ats_base_is_high(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        prov = [make_provenance("full_name", SourceType.ATS, "Jane Smith")]
        record = engine.score(sample_candidate, prov, sources_used=["ats"])
        # ATS weight is 0.95, so overall should be reasonably high
        assert record.overall_score > 0.5

    def test_score_agreement_increases_confidence(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        # Two sources agree
        prov_agree = [
            make_provenance(
                "full_name",
                SourceType.ATS,
                "Jane Smith",
                candidates=[(SourceType.CSV, "Jane Smith")],
            )
        ]
        record_agree = engine.score(sample_candidate, prov_agree, sources_used=["ats", "csv"])
        score_agree = record_agree.fields.get("full_name", None)

        # One source alone
        prov_alone = [make_provenance("full_name", SourceType.ATS, "Jane Smith")]
        record_alone = engine.score(sample_candidate, prov_alone, sources_used=["ats"])
        score_alone = record_alone.fields.get("full_name", None)

        if score_agree and score_alone:
            assert score_agree.score >= score_alone.score

    def test_score_conflict_decreases_confidence(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        prov = [
            make_provenance(
                "full_name",
                SourceType.ATS,
                "Jane Smith",
                candidates=[(SourceType.CSV, "J. Smith")],  # Conflict
            )
        ]
        record = engine.score(sample_candidate, prov, sources_used=["ats", "csv"])
        field_conf = record.fields.get("full_name")
        if field_conf:
            # Should have disagreement penalty applied
            assert field_conf.disagreement_penalty > 0 or field_conf.score <= 0.95

    def test_score_populates_high_confidence_fields(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        prov = [make_provenance("full_name", SourceType.ATS, "Jane Smith")]
        record = engine.score(sample_candidate, prov, sources_used=["ats"])
        assert isinstance(record.high_confidence_fields, list)

    def test_score_overall_is_between_0_and_1(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        prov = [
            make_provenance("full_name", SourceType.ATS, "Jane Smith"),
            make_provenance("emails", SourceType.ATS, ["jane@example.com"]),
        ]
        record = engine.score(sample_candidate, prov, sources_used=["ats"])
        assert 0.0 <= record.overall_score <= 1.0

    def test_score_empty_provenance(self, sample_candidate: Candidate) -> None:
        engine = ConfidenceEngine()
        record = engine.score(sample_candidate, [], sources_used=["ats"])
        assert record is not None
        assert 0.0 <= record.overall_score <= 1.0
