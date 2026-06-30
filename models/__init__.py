"""
models package

All canonical domain models for CandidateFusion AI.

Import from this package, not from the submodules, so that internal
restructuring never breaks downstream consumers.
"""

from models.candidate import (
    Candidate,
    Certification,
    Education,
    Experience,
    Language,
    Location,
    Project,
    Skill,
    SocialLink,
)
from models.confidence import ConfidenceRecord, FieldConfidence
from models.extracted import ExtractedCandidate
from models.metadata import PipelineMetadata, SourceType
from models.provenance import ProvenanceRecord

__all__ = [
    # Candidate domain
    "Candidate",
    "Experience",
    "Education",
    "Project",
    "Certification",
    "Skill",
    "SocialLink",
    "Location",
    "Language",
    # Confidence
    "ConfidenceRecord",
    "FieldConfidence",
    # Provenance
    "ProvenanceRecord",
    # Metadata
    "PipelineMetadata",
    "SourceType",
    # Extraction intermediate
    "ExtractedCandidate",
]
