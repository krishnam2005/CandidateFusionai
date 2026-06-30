"""
confidence.engine — Confidence scoring for merged candidate profiles.

Confidence Score Computation
============================

For each scored field:

  base_score = SOURCE_WEIGHTS[primary_source]

  agreement_bonus = 0.05 × (n_agreeing_sources - 1)
    where "agreeing" means the normalized value is the same across sources

  disagreement_penalty = 0.10 × n_conflicting_sources

  field_score = clamp(base_score + agreement_bonus - disagreement_penalty, 0, 1)

Overall score = weighted mean of all field scores, where field weights reflect
the importance of each field to profile completeness.

Field importance weights (internal):
  full_name: 1.0
  emails:    1.0
  phones:    0.8
  location:  0.7
  summary:   0.6
  skills:    0.9
  experience:0.9
  education: 0.8

All other fields: 0.5
"""

from __future__ import annotations

from models.candidate import Candidate
from models.confidence import ConfidenceRecord, FieldConfidence
from models.provenance import FieldProvenance
from utils.logging import get_logger

log = get_logger(__name__)

# Source base weights (replicated here; truth is in settings but engine is self-contained)
_SOURCE_WEIGHTS: dict[str, float] = {
    "ats": 0.95,
    "csv": 0.92,
    "resume": 0.90,
    "github": 0.80,
    "notes": 0.70,
    "unknown": 0.50,
}

# Field importance weights for overall score computation
_FIELD_IMPORTANCE: dict[str, float] = {
    "full_name": 1.0,
    "emails": 1.0,
    "phones": 0.8,
    "location": 0.7,
    "summary": 0.6,
    "skills": 0.9,
    "experience": 0.9,
    "education": 0.8,
    "projects": 0.5,
    "certifications": 0.5,
    "social_links": 0.4,
    "languages": 0.3,
    "headline": 0.5,
    "years_of_experience": 0.7,
}

# Bonuses and penalties
_AGREEMENT_BONUS = 0.05
_DISAGREEMENT_PENALTY = 0.10
_HIGH_CONFIDENCE_THRESHOLD = 0.90
_LOW_CONFIDENCE_THRESHOLD = 0.70


class ConfidenceEngine:
    """
    Computes per-field and aggregate confidence scores for a merged profile.

    Accepts a list of FieldProvenance records (produced by MergeEngine)
    and uses them to determine source agreement/disagreement.
    """

    def score(
        self,
        candidate: Candidate,
        provenance_records: list[FieldProvenance],
        sources_used: list[str],
    ) -> ConfidenceRecord:
        """
        Compute confidence scores for all fields in the candidate profile.

        Parameters
        ----------
        candidate:
            The merged candidate profile.
        provenance_records:
            Provenance records from the merge engine.
        sources_used:
            List of source names (strings) that participated in the merge.

        Returns
        -------
        ConfidenceRecord
            Aggregate and per-field confidence scores.
        """
        provenance_by_field = {p.field_name: p for p in provenance_records}

        field_scores: dict[str, FieldConfidence] = {}

        # ── Score fields with explicit provenance ─────────────────────────
        for field_name, prov in provenance_by_field.items():
            fc = self._score_field_from_provenance(field_name, prov)
            field_scores[field_name] = fc

        # ── Score fields without provenance (simple presence check) ───────
        self._score_simple_presence(candidate, field_scores, sources_used)

        # ── Compute overall score ─────────────────────────────────────────
        overall = self._compute_overall(field_scores)

        high_conf = [f for f, fc in field_scores.items() if fc.score >= _HIGH_CONFIDENCE_THRESHOLD]
        low_conf = [f for f, fc in field_scores.items() if fc.score < _LOW_CONFIDENCE_THRESHOLD]

        record = ConfidenceRecord(
            overall_score=overall,
            fields=field_scores,
            high_confidence_fields=sorted(high_conf),
            low_confidence_fields=sorted(low_conf),
            sources_used=sources_used,
        )

        log.info(
            "confidence_scored",
            overall=round(overall, 3),
            high_confidence_count=len(high_conf),
            low_confidence_count=len(low_conf),
        )

        return record

    def _score_field_from_provenance(
        self,
        field_name: str,
        prov: FieldProvenance,
    ) -> FieldConfidence:
        """Compute FieldConfidence from a FieldProvenance record."""
        base_score = _SOURCE_WEIGHTS.get(prov.selected.source.value, 0.5)

        # Agreement: how many other candidates provided the same value?
        all_values = [str(c.value).lower().strip() for c in prov.candidates]
        winning_value = str(prov.selected.value).lower().strip()

        agreeing = max(0, sum(1 for v in all_values if v == winning_value) - 1)  # exclude self
        disagreeing = sum(1 for v in all_values if v != winning_value)

        agreement_bonus = _AGREEMENT_BONUS * max(0, agreeing)
        disagreement_penalty = _DISAGREEMENT_PENALTY * max(0, disagreeing)

        score = min(1.0, max(0.0, base_score + agreement_bonus - disagreement_penalty))

        explanation = (
            f"Base: {base_score:.2f} (source={prov.selected.source})"
            + (f" +{agreement_bonus:.2f} (agreement)" if agreement_bonus > 0 else "")
            + (f" -{disagreement_penalty:.2f} (conflict)" if disagreement_penalty > 0 else "")
        )

        return FieldConfidence(
            field_name=field_name,
            score=round(score, 4),
            base_score=base_score,
            agreement_bonus=round(agreement_bonus, 4),
            disagreement_penalty=round(disagreement_penalty, 4),
            sources_agreed=agreeing,
            sources_disagreed=disagreeing,
            explanation=explanation,
        )

    def _score_simple_presence(
        self,
        candidate: Candidate,
        field_scores: dict[str, FieldConfidence],
        sources_used: list[str],
    ) -> None:
        """Score fields without provenance records based on presence and source count."""
        source_count = len(sources_used)
        base_score = _SOURCE_WEIGHTS.get(sources_used[0] if sources_used else "unknown", 0.5)

        fields_to_check = {
            "full_name": candidate.full_name,
            "emails": candidate.emails,
            "phones": candidate.phones,
            "skills": candidate.skills,
            "experience": candidate.experience,
            "education": candidate.education,
        }

        for field, value in fields_to_check.items():
            if field in field_scores:
                continue  # Already scored via provenance

            has_value = bool(value)
            score = base_score if has_value else 0.0

            field_scores[field] = FieldConfidence(
                field_name=field,
                score=round(score, 4),
                base_score=base_score,
                explanation=f"Presence-based: {'present' if has_value else 'missing'}",
            )

    def _compute_overall(self, field_scores: dict[str, FieldConfidence]) -> float:
        """Compute weighted mean of all field confidence scores."""
        if not field_scores:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for field_name, fc in field_scores.items():
            weight = _FIELD_IMPORTANCE.get(field_name, 0.5)
            weighted_sum += fc.score * weight
            total_weight += weight

        return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0
