"""
api.routes — FastAPI route definitions for CandidateFusion AI.

Endpoint: POST /api/v1/transform

Accepts multipart/form-data with optional file uploads and a GitHub URL.
Writes uploaded files to a temporary directory, runs the pipeline, and
returns the canonical JSON profile.

Error handling:
  - 400: Invalid request (no sources provided, invalid config JSON)
  - 422: FastAPI validation error (handled automatically)
  - 500: Internal pipeline error
  - Partial failures (one source fails) result in 200 with metadata indicating
    which sources failed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from config.settings import get_settings
from services.pipeline import Pipeline, PipelineInput
from utils.logging import get_logger

log = get_logger(__name__)

transform_router = APIRouter(tags=["Transform"])


class ORJSONResponse(JSONResponse):
    """Custom JSONResponse that uses orjson for fast serialization."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_INDENT_2)


@transform_router.post(
    "/transform",
    response_class=ORJSONResponse,
    summary="Transform candidate data from multiple sources",
    description=(
        "Upload one or more candidate data sources and receive a unified "
        "canonical candidate profile with confidence scoring and provenance tracking."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Successfully transformed candidate profile"},
        400: {"description": "No input sources provided or invalid configuration"},
        500: {"description": "Internal pipeline error"},
    },
)
async def transform_candidate(
    csv_file: Annotated[
        UploadFile | None,
        File(description="Recruiter CSV file"),
    ] = None,
    ats_file: Annotated[
        UploadFile | None,
        File(description="ATS JSON file"),
    ] = None,
    resume_file: Annotated[
        UploadFile | None,
        File(description="Resume PDF file"),
    ] = None,
    github_url: Annotated[
        str | None,
        Form(description="GitHub profile URL or username"),
    ] = None,
    notes_file: Annotated[
        UploadFile | None,
        File(description="Recruiter notes text file"),
    ] = None,
    config_file: Annotated[
        UploadFile | None,
        File(description="Output configuration JSON file"),
    ] = None,
) -> ORJSONResponse:
    """
    Transform candidate data from multiple sources into a canonical profile.

    Accepts multipart/form-data with optional file uploads.
    At least one source (file or GitHub URL) must be provided.
    """
    settings = get_settings()

    # Validate at least one source
    has_source = any([csv_file, ats_file, resume_file, github_url, notes_file])
    if not has_source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one input source is required. "
                   "Provide one or more of: csv_file, ats_file, resume_file, github_url, notes_file.",
        )

    log.info(
        "api_transform_request",
        has_csv=csv_file is not None,
        has_ats=ats_file is not None,
        has_resume=resume_file is not None,
        has_github=github_url is not None,
        has_notes=notes_file is not None,
    )

    # Write uploaded files to a temp directory
    with tempfile.TemporaryDirectory(prefix="candidate_fusion_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        csv_path = await _save_upload(csv_file, tmp_path, "recruiter.csv")
        ats_path = await _save_upload(ats_file, tmp_path, "ats.json")
        resume_path = await _save_upload(resume_file, tmp_path, "resume.pdf")
        notes_path = await _save_upload(notes_file, tmp_path, "notes.txt")
        config_path = await _save_upload(config_file, tmp_path, "output_config.json")

        # Use default config if not provided
        effective_config_path = config_path or settings.pipeline_default_config_path

        pipeline_inputs = PipelineInput(
            csv_path=csv_path,
            ats_path=ats_path,
            resume_path=resume_path,
            github_url=github_url,
            notes_path=notes_path,
            output_config_path=effective_config_path,
        )

        try:
            pipeline = Pipeline(settings=settings)
            result = pipeline.run(pipeline_inputs)
        except ValueError as exc:
            log.warning("api_pipeline_value_error", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            log.error("api_pipeline_error", error=str(exc), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Pipeline error: {exc}",
            ) from exc

        # Re-parse the orjson bytes to a Python dict for the response
        output_data = orjson.loads(result.output_json)

        log.info(
            "api_transform_complete",
            candidate=result.candidate.display_name,
            confidence=result.candidate.confidence.overall_score if result.candidate.confidence else None,
            sources_succeeded=len(result.metadata.sources_succeeded),
        )

        return ORJSONResponse(content=output_data)


async def _save_upload(
    upload: UploadFile | None,
    directory: Path,
    filename: str,
) -> Path | None:
    """Save an uploaded file to a temp directory. Returns None if no upload."""
    if upload is None:
        return None

    contents = await upload.read()
    if not contents:
        return None

    dest = directory / filename
    dest.write_bytes(contents)
    return dest
