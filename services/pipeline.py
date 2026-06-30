"""
services.pipeline — Main pipeline orchestrator (CandidateFusion AI).

This is the heart of the system.  The Pipeline class coordinates the
end-to-end transformation flow:

  1. Source Detection — Identify which sources were provided.
  2. Extraction       — Run the appropriate extractor for each source.
  3. Canonical Mapping— Transform each ExtractedCandidate → Candidate.
  4. Merge            — Combine all Candidates into one merged profile.
  5. Confidence       — Score the merged profile.
  6. Provenance       — Attach provenance to the merged profile.
  7. Validation       — Validate the merged profile.
  8. Projection       — Apply output config and serialize.

Design:
  - The Pipeline is stateless — each run is independent.
  - Extractor failures are non-fatal by default (partial results are used).
  - Full execution metadata is attached to the output profile.
  - All significant events are logged with structlog.
"""

from __future__ import annotations

import time
from pathlib import Path

from confidence.engine import ConfidenceEngine
from config.settings import Settings, get_settings
from extractors.base import ExtractorError
from extractors.factory import ExtractorFactory
from mergers.merge_engine import MergeEngine
from models.candidate import Candidate
from models.metadata import PipelineMetadata, SourceMeta, SourceType
from models.provenance import FieldProvenance
from projection.projector import OutputConfig, Projector
from services.canonical_mapper import CanonicalMapper
from validators.validation_engine import ValidationEngine
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)


class PipelineInput:
    """Typed container for all possible pipeline inputs."""

    def __init__(
        self,
        csv_path: Path | None = None,
        ats_path: Path | None = None,
        resume_path: Path | None = None,
        github_url: str | None = None,
        notes_path: Path | None = None,
        output_config_path: Path | None = None,
    ) -> None:
        self.csv_path = csv_path
        self.ats_path = ats_path
        self.resume_path = resume_path
        self.github_url = github_url
        self.notes_path = notes_path
        self.output_config_path = output_config_path

    def sources_provided(self) -> list[tuple[SourceType, str]]:
        """Return list of (source_type, source_path_or_url) for all provided sources."""
        sources = []
        if self.ats_path:
            sources.append((SourceType.ATS, str(self.ats_path)))
        if self.csv_path:
            sources.append((SourceType.CSV, str(self.csv_path)))
        if self.resume_path:
            sources.append((SourceType.RESUME, str(self.resume_path)))
        if self.github_url:
            sources.append((SourceType.GITHUB, self.github_url))
        if self.notes_path:
            sources.append((SourceType.NOTES, str(self.notes_path)))
        return sources


class PipelineResult:
    """Result object returned by the pipeline."""

    def __init__(
        self,
        candidate: Candidate,
        provenance_records: list[FieldProvenance],
        output_dict: dict,
        output_json: bytes,
        metadata: PipelineMetadata,
        validation_report: object,
    ) -> None:
        self.candidate = candidate
        self.provenance_records = provenance_records
        self.output_dict = output_dict
        self.output_json = output_json
        self.metadata = metadata
        self.validation_report = validation_report

    @property
    def succeeded(self) -> bool:
        return self.metadata.validation_passed


class Pipeline:
    """
    End-to-end candidate data transformation pipeline.

    Inject dependencies through the constructor for testability.
    All components can be swapped with mocks in tests.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        factory: ExtractorFactory | None = None,
        mapper: CanonicalMapper | None = None,
        merge_engine: MergeEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        validation_engine: ValidationEngine | None = None,
        projector: Projector | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._factory = factory or ExtractorFactory(self._settings)
        self._mapper = mapper or CanonicalMapper()
        self._merge_engine = merge_engine or MergeEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._validation_engine = validation_engine or ValidationEngine()
        self._projector = projector or Projector()

    def run(self, inputs: PipelineInput) -> PipelineResult:
        """
        Execute the full transformation pipeline.

        Parameters
        ----------
        inputs:
            All source inputs for this run.

        Returns
        -------
        PipelineResult
            The merged profile, provenance, output JSON, and metadata.
        """
        run_start = time.perf_counter()
        metadata = PipelineMetadata()

        sources_provided = inputs.sources_provided()
        if not sources_provided:
            raise ValueError("No input sources provided. At least one source is required.")

        metadata.sources_requested = [s for s, _ in sources_provided]
        metadata.output_config_path = str(inputs.output_config_path) if inputs.output_config_path else None

        log.info(
            "pipeline_run_start",
            run_id=str(metadata.run_id),
            sources=[s.value for s in metadata.sources_requested],
        )

        # ── Step 1 & 2: Extract from each source ─────────────────────────
        candidates_by_source: dict[SourceType, Candidate] = {}
        sources_used: list[str] = []

        for source_type, source_path in sources_provided:
            source_meta = SourceMeta(source=source_type, raw_path=source_path)
            source_start = time.perf_counter()

            try:
                with timed(f"extraction_{source_type}", source=source_path):
                    extractor = self._factory.create(source_type)
                    extracted = extractor.extract(source_path)

                source_meta.extraction_duration_ms = (time.perf_counter() - source_start) * 1000
                source_meta.record_count = 1

                # ── Step 3: Canonical mapping ─────────────────────────────
                with timed(f"mapping_{source_type}"):
                    canonical = self._mapper.map(extracted)

                candidates_by_source[source_type] = canonical
                metadata.sources_succeeded.append(source_type)
                sources_used.append(source_type.value)

                log.info(
                    "source_processed",
                    source=source_type.value,
                    path=source_path,
                    duration_ms=round(source_meta.extraction_duration_ms, 2),
                )

            except ExtractorError as exc:
                source_meta.error = str(exc)
                metadata.sources_failed.append(source_type)
                log.warning(
                    "source_extraction_failed",
                    source=source_type.value,
                    path=source_path,
                    error=str(exc),
                )

            except Exception as exc:
                source_meta.error = f"Unexpected error: {exc}"
                metadata.sources_failed.append(source_type)
                log.error(
                    "source_extraction_unexpected_error",
                    source=source_type.value,
                    path=source_path,
                    error=str(exc),
                    exc_info=True,
                )

            finally:
                metadata.source_details.append(source_meta)

        if not candidates_by_source:
            raise ValueError(
                "All source extractions failed. Cannot produce a candidate profile. "
                f"Failed sources: {[s.value for s in metadata.sources_failed]}"
            )

        # ── Step 4: Merge ─────────────────────────────────────────────────
        with timed("merge", source_count=len(candidates_by_source)):
            merged_candidate, provenance_records = self._merge_engine.merge(candidates_by_source)

        # ── Step 5: Confidence Scoring ────────────────────────────────────
        with timed("confidence_scoring"):
            confidence = self._confidence_engine.score(
                candidate=merged_candidate,
                provenance_records=provenance_records,
                sources_used=sources_used,
            )
        merged_candidate = merged_candidate.model_copy(update={"confidence": confidence})

        # ── Step 6: Attach provenance and metadata ─────────────────────────
        merged_candidate = merged_candidate.model_copy(update={"provenance": provenance_records})
        merged_candidate = merged_candidate.model_copy(update={"metadata": metadata})

        # ── Step 7: Validation ────────────────────────────────────────────
        with timed("validation"):
            validation_report = self._validation_engine.validate(
                merged_candidate,
                strict=self._settings.validation_strict_mode,
            )

        metadata.validation_passed = validation_report.is_valid
        metadata.validation_warnings = len(validation_report.warnings)
        metadata.validation_errors = len(validation_report.errors)

        if validation_report.errors:
            log.warning(
                "validation_errors_found",
                error_count=len(validation_report.errors),
                errors=[r.message for r in validation_report.errors],
            )

        # ── Step 8: Projection ────────────────────────────────────────────
        output_config: OutputConfig
        if inputs.output_config_path and inputs.output_config_path.exists():
            try:
                output_config = OutputConfig.from_file(inputs.output_config_path)
                log.info("output_config_loaded", path=str(inputs.output_config_path))
            except ValueError as exc:
                log.warning("output_config_load_failed", error=str(exc))
                output_config = OutputConfig.default()
        else:
            output_config = OutputConfig.default()

        with timed("projection"):
            output_dict = self._projector.project(merged_candidate, provenance_records, output_config)
            output_json = self._projector.to_json(merged_candidate, provenance_records, output_config)

        # ── Finalize metadata ─────────────────────────────────────────────
        total_ms = (time.perf_counter() - run_start) * 1000
        metadata.mark_completed(total_ms)
        # Update candidate with final metadata
        merged_candidate = merged_candidate.model_copy(update={"metadata": metadata})

        log.info(
            "pipeline_run_complete",
            run_id=str(metadata.run_id),
            candidate=merged_candidate.display_name,
            duration_ms=round(total_ms, 2),
            sources_succeeded=len(metadata.sources_succeeded),
            sources_failed=len(metadata.sources_failed),
            overall_confidence=confidence.overall_score,
            validation_passed=metadata.validation_passed,
        )

        return PipelineResult(
            candidate=merged_candidate,
            provenance_records=provenance_records,
            output_dict=output_dict,
            output_json=output_json,
            metadata=metadata,
            validation_report=validation_report,
        )
