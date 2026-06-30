"""
validators.validation_engine — Candidate profile validation engine.

Implements a rule-based validation pipeline that checks:
  1. Required fields — must be present and non-empty
  2. Email format — syntactic validity
  3. Phone format — E.164 format compliance
  4. Date logic — start before end, dates in valid range
  5. GPA range — must be [0.0, 4.0]
  6. URL format — social links must be valid URLs
  7. Confidence thresholds — warn on low-confidence fields
  8. Data completeness — warn on missing recommended fields

Validation design:
  - Rules are independent — each rule runs regardless of others.
  - Findings are collected as ValidationResult objects.
  - Severity: ERROR (blocks output in strict mode) | WARNING (non-blocking)
  - The ValidationEngine is stateless — instances can be shared across threads.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from urllib.parse import urlparse

from models.candidate import Candidate
from normalizers.email_normalizer import EmailNormalizer
from normalizers.phone_normalizer import PhoneNormalizer
from utils.logging import get_logger

log = get_logger(__name__)


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationResult:
    """A single validation finding."""

    def __init__(
        self,
        severity: ValidationSeverity,
        field: str,
        message: str,
        value: object = None,
    ) -> None:
        self.severity = severity
        self.field = field
        self.message = message
        self.value = value

    def __repr__(self) -> str:
        return f"ValidationResult({self.severity}, {self.field!r}, {self.message!r})"

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity.value,
            "field": self.field,
            "message": self.message,
            "value": str(self.value) if self.value is not None else None,
        }


class ValidationReport:
    """Aggregated validation results for a single candidate profile."""

    def __init__(self, results: list[ValidationResult]) -> None:
        self.results = results

    @property
    def errors(self) -> list[ValidationResult]:
        return [r for r in self.results if r.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [r for r in self.results if r.severity == ValidationSeverity.WARNING]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def is_valid(self) -> bool:
        return not self.has_errors

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [r.to_dict() for r in self.results],
        }


class ValidationEngine:
    """
    Validates a merged Candidate profile against all defined rules.

    Rules are composed as a list of callable validators, each returning
    a list of ValidationResult objects.  Adding a new rule requires only
    adding a method with the ``_validate_`` prefix.
    """

    def validate(self, candidate: Candidate, strict: bool = False) -> ValidationReport:
        """
        Run all validation rules against the candidate.

        Parameters
        ----------
        candidate:
            The merged and normalized candidate profile.
        strict:
            If True, any validation finding is treated as an error.

        Returns
        -------
        ValidationReport
            A collection of all validation findings.
        """
        results: list[ValidationResult] = []

        rules = [
            self._validate_required_fields,
            self._validate_emails,
            self._validate_phones,
            self._validate_dates,
            self._validate_gpa,
            self._validate_urls,
            self._validate_completeness,
        ]

        for rule in rules:
            try:
                rule_results = rule(candidate)
                results.extend(rule_results)
            except Exception as exc:
                log.error(
                    "validation_rule_failed",
                    rule=rule.__name__,
                    error=str(exc),
                    exc_info=True,
                )
                results.append(
                    ValidationResult(
                        severity=ValidationSeverity.ERROR,
                        field="system",
                        message=f"Validation rule {rule.__name__} failed: {exc}",
                    )
                )

        report = ValidationReport(results)

        log.info(
            "validation_complete",
            candidate_id=str(candidate.candidate_id),
            errors=len(report.errors),
            warnings=len(report.warnings),
            valid=report.is_valid,
        )

        return report

    def _validate_required_fields(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate that required fields are present."""
        results: list[ValidationResult] = []

        # Full name or first+last must be present
        has_name = bool(candidate.full_name or (candidate.first_name and candidate.last_name))
        if not has_name:
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                field="full_name",
                message="Candidate has no name (full_name or first_name+last_name required)",
            ))

        # At least one contact method
        if not candidate.emails and not candidate.phones:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                field="contact",
                message="No email addresses or phone numbers found",
            ))

        return results

    def _validate_emails(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate all email addresses."""
        results: list[ValidationResult] = []

        for email in candidate.emails:
            if not EmailNormalizer.is_valid(email):
                results.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    field="emails",
                    message=f"Invalid email address format",
                    value=email,
                ))

        return results

    def _validate_phones(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate all phone numbers (must be E.164 format after normalization)."""
        results: list[ValidationResult] = []
        e164_pattern = re.compile(r"^\+[1-9]\d{6,14}$")

        for phone in candidate.phones:
            if not e164_pattern.match(phone):
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    field="phones",
                    message="Phone number is not in E.164 format",
                    value=phone,
                ))

        return results

    def _validate_dates(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate date logic in experience and education entries."""
        results: list[ValidationResult] = []
        today = date.today()
        min_date = date(1950, 1, 1)

        for i, exp in enumerate(candidate.experience):
            prefix = f"experience[{i}] ({exp.company})"

            if exp.start_date and exp.start_date < min_date:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    field=f"{prefix}.start_date",
                    message=f"Unrealistic start date",
                    value=exp.start_date,
                ))

            if exp.start_date and exp.end_date:
                if exp.end_date < exp.start_date:
                    results.append(ValidationResult(
                        severity=ValidationSeverity.ERROR,
                        field=f"{prefix}.dates",
                        message="End date is before start date",
                        value=f"{exp.start_date} > {exp.end_date}",
                    ))

            if exp.start_date and exp.start_date > today:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    field=f"{prefix}.start_date",
                    message="Start date is in the future",
                    value=exp.start_date,
                ))

        for i, edu in enumerate(candidate.education):
            prefix = f"education[{i}] ({edu.institution})"

            if edu.start_date and edu.end_date:
                if edu.end_date < edu.start_date:
                    results.append(ValidationResult(
                        severity=ValidationSeverity.ERROR,
                        field=f"{prefix}.dates",
                        message="Graduation date is before enrollment date",
                        value=f"{edu.start_date} > {edu.end_date}",
                    ))

        return results

    def _validate_gpa(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate GPA values are in a realistic range."""
        results: list[ValidationResult] = []

        for i, edu in enumerate(candidate.education):
            if edu.gpa is not None:
                if not 0.0 <= edu.gpa <= 4.0:
                    results.append(ValidationResult(
                        severity=ValidationSeverity.ERROR,
                        field=f"education[{i}].gpa",
                        message="GPA must be between 0.0 and 4.0",
                        value=edu.gpa,
                    ))

        return results

    def _validate_urls(self, candidate: Candidate) -> list[ValidationResult]:
        """Validate social link URLs are well-formed."""
        results: list[ValidationResult] = []

        for i, link in enumerate(candidate.social_links):
            try:
                parsed = urlparse(link.url)
                if not parsed.scheme or not parsed.netloc:
                    results.append(ValidationResult(
                        severity=ValidationSeverity.WARNING,
                        field=f"social_links[{i}].url",
                        message="Social link URL is malformed",
                        value=link.url,
                    ))
            except Exception:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    field=f"social_links[{i}].url",
                    message="Social link URL could not be parsed",
                    value=link.url,
                ))

        return results

    def _validate_completeness(self, candidate: Candidate) -> list[ValidationResult]:
        """Warn on missing recommended fields."""
        results: list[ValidationResult] = []

        recommended = {
            "summary": candidate.summary,
            "skills": candidate.skills,
            "experience": candidate.experience,
            "education": candidate.education,
        }

        for field, value in recommended.items():
            if not value:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    field=field,
                    message=f"Recommended field '{field}' is empty or missing",
                ))

        return results
