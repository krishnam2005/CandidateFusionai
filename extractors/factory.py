"""
extractors.factory — Factory for creating extractor instances.

The Factory pattern centralises extractor instantiation so that:
  1. The pipeline never directly imports concrete extractor classes.
  2. Adding a new extractor requires only registering it in the factory.
  3. Dependency injection (e.g., API clients, settings) happens here.

Design: ``ExtractorFactory`` maintains a registry of extractor classes keyed
by SourceType.  ``create()`` instantiates on demand (no singletons — extractors
are cheap to create and may carry per-call state in the future).
"""

from __future__ import annotations

from config.settings import Settings, get_settings
from extractors.ats_json import ATSJsonExtractor
from extractors.base import BaseExtractor
from extractors.csv_extractor import CSVExtractor
from extractors.github_extractor import GitHubExtractor
from extractors.notes_extractor import NotesExtractor
from extractors.pdf_extractor import PDFExtractor
from models.metadata import SourceType
from utils.logging import get_logger

log = get_logger(__name__)


class ExtractorFactory:
    """
    Creates configured extractor instances.

    Registry is populated at class definition time.  To add a new extractor:
      1. Implement ``BaseExtractor`` in a new module.
      2. Import it here.
      3. Add it to ``_REGISTRY``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create(self, source_type: SourceType) -> BaseExtractor:
        """
        Instantiate and return an extractor for the given source type.

        Raises
        ------
        ValueError
            If no extractor is registered for the requested source type.
        """
        match source_type:
            case SourceType.ATS:
                return ATSJsonExtractor()
            case SourceType.CSV:
                return CSVExtractor()
            case SourceType.RESUME:
                return PDFExtractor(
                    max_pages=self._settings.pdf_max_pages,
                    strategy=self._settings.pdf_text_extraction_strategy,
                )
            case SourceType.GITHUB:
                return GitHubExtractor(
                    token=self._settings.github_token,
                    base_url=self._settings.github_api_base_url,
                    timeout=self._settings.github_api_timeout_seconds,
                    max_retries=self._settings.github_api_max_retries,
                )
            case SourceType.NOTES:
                return NotesExtractor()
            case _:
                raise ValueError(
                    f"No extractor registered for source type: {source_type!r}. "
                    f"Supported types: {[st.value for st in SourceType if st != SourceType.UNKNOWN]}"
                )

    def available_sources(self) -> list[SourceType]:
        """Return list of source types that have registered extractors."""
        return [
            SourceType.ATS,
            SourceType.CSV,
            SourceType.RESUME,
            SourceType.GITHUB,
            SourceType.NOTES,
        ]
