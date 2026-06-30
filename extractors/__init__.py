"""
extractors package — Source-specific data extractors.

All extractors implement the BaseExtractor interface.  Adding a new source
requires only creating a new extractor class that inherits from BaseExtractor
— no changes to the pipeline, factory, or any other module.

This adheres to the Open/Closed Principle.
"""

from extractors.base import BaseExtractor, ExtractorError
from extractors.ats_json import ATSJsonExtractor
from extractors.csv_extractor import CSVExtractor
from extractors.github_extractor import GitHubExtractor
from extractors.notes_extractor import NotesExtractor
from extractors.pdf_extractor import PDFExtractor
from extractors.factory import ExtractorFactory

__all__ = [
    "BaseExtractor",
    "ExtractorError",
    "ATSJsonExtractor",
    "CSVExtractor",
    "GitHubExtractor",
    "NotesExtractor",
    "PDFExtractor",
    "ExtractorFactory",
]
