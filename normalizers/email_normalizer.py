"""
normalizers.email_normalizer — Email address normalization and deduplication.

Uses the ``email-validator`` library for RFC-compliant validation and
lowercases the local part after splitting on ``@``.  Gmail dot-trick and
plus-address normalization are applied to further reduce duplicates.

Why email-validator over re-based validation?
  - Handles internationalized email addresses (IDN domains).
  - Validates MX records optionally.
  - More robust against edge cases that simple regex misses.
"""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

from utils.logging import get_logger

log = get_logger(__name__)


class EmailNormalizer:
    """
    Normalizes and validates email addresses.

    Normalization steps:
      1. Strip whitespace.
      2. Lowercase the entire address.
      3. Remove Gmail-specific dots from local part.
      4. Remove Gmail/other plus-address suffixes.
      5. Validate via ``email-validator`` (syntax only, no DNS by default).
    """

    @staticmethod
    def normalize(email: str | None) -> str | None:
        """
        Normalize a single email address.

        Returns None if the email is invalid or empty.
        """
        if not email:
            return None

        email = email.strip().lower()

        try:
            validated = validate_email(email, check_deliverability=False)
            normalized = validated.normalized
        except EmailNotValidError as exc:
            log.debug("email_invalid", email=email, reason=str(exc))
            return None

        # Apply plus-address removal for common providers
        local, _, domain = normalized.partition("@")
        if "+" in local:
            local = local.split("+")[0]

        # Remove Gmail dots from local part
        if domain in ("gmail.com", "googlemail.com"):
            local = local.replace(".", "")

        return f"{local}@{domain}"

    @staticmethod
    def normalize_list(emails: list[str]) -> list[str]:
        """
        Normalize a list of email addresses, removing invalids and duplicates.

        Order is preserved; later duplicates are dropped.
        """
        seen: set[str] = set()
        result: list[str] = []
        for raw in emails:
            normalized = EmailNormalizer.normalize(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @staticmethod
    def is_valid(email: str) -> bool:
        """Return True if the email address is syntactically valid."""
        try:
            validate_email(email, check_deliverability=False)
            return True
        except EmailNotValidError:
            return False
