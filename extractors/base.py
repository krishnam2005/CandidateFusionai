"""
extractors.base — Abstract base class for all source extractors.

This defines the Strategy interface that every extractor must implement.
The pipeline works exclusively through this interface, ensuring that:

  1. All extractors are interchangeable from the pipeline's perspective.
  2. New extractors can be added without touching pipeline code (OCP).
  3. The interface enforces a consistent contract (ISP — single responsibility).

Design decisions:
  - ``extract()`` is abstract and synchronous.  For async I/O (e.g., streaming
    PDF processing), subclasses should use asyncio internally and expose the
    synchronous wrapper.  This keeps the pipeline orchestrator simple.
  - Extractor failure is communicated via ``ExtractorError`` (a rich exception),
    not via Optional return values.  This makes error paths explicit and forces
    callers to handle them.
  - ``source_type`` is a class-level attribute (not constructor arg) to avoid
    accidental misconfiguration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from models.extracted import ExtractedCandidate
from models.metadata import SourceType
from utils.logging import get_logger

log = get_logger(__name__)


class ExtractorError(Exception):
    """
    Raised by extractors when extraction fails in a recoverable way.

    Carries the source type and original exception for structured error
    handling in the pipeline orchestrator.
    """

    def __init__(
        self,
        message: str,
        source: SourceType,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.cause = cause

    def __str__(self) -> str:
        base = super().__str__()
        return f"[{self.source}] {base}" + (f" (caused by: {self.cause})" if self.cause else "")


class BaseExtractor(ABC):
    """
    Abstract base class for all candidate data source extractors.

    Every concrete extractor:
      - Declares its ``source_type`` as a class attribute.
      - Implements ``extract()`` to return an ``ExtractedCandidate``.
      - Raises ``ExtractorError`` on failure (never returns None).
      - Logs all significant events using structlog.
    """

    #: Subclasses MUST override this with the correct SourceType
    source_type: SourceType

    @abstractmethod
    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from the given source.

        Parameters
        ----------
        source:
            The source to extract from.  Depending on the extractor, this
            may be a filesystem path (str or Path) or a URL (str).

        Returns
        -------
        ExtractedCandidate
            An intermediate representation of the extracted data.
            All fields are optional — extractors only populate what they find.

        Raises
        ------
        ExtractorError
            If extraction fails due to missing file, corrupt data,
            network error, or any other recoverable condition.
        """
        ...

    def safe_extract(self, source: str | Path) -> ExtractedCandidate | None:
        """
        Wrapper around ``extract()`` that catches ``ExtractorError`` and
        returns None, logging the error as a warning.

        Use this in the pipeline orchestrator when partial failure is
        acceptable (i.e., missing one source should not abort the run).
        """
        try:
            return self.extract(source)
        except ExtractorError as exc:
            log.warning(
                "extractor_failed",
                source_type=self.source_type,
                input=str(source),
                error=str(exc),
            )
            return None
        except Exception as exc:
            log.error(
                "extractor_unexpected_error",
                source_type=self.source_type,
                input=str(source),
                error=str(exc),
                exc_info=True,
            )
            return None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source_type={self.source_type!r})"
