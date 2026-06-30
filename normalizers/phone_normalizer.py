"""
normalizers.phone_normalizer — Phone number normalization to E.164 format.

Uses Google's ``phonenumbers`` library — the same library used in production
by major telecom and fintech companies — for parsing and formatting.

E.164 format: +[country_code][subscriber_number], e.g. "+14155552671"

Why phonenumbers?
  - Handles local formats (e.g., "(415) 555-2671", "415.555.2671").
  - Supports 250+ country dial codes.
  - Validates number length and subscriber ranges per country.
  - No dependency on external APIs.
"""

from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

from utils.logging import get_logger

log = get_logger(__name__)

# Default region when no country code is present in the raw string.
# US is the most common default for North American talent platforms.
_DEFAULT_REGION = "US"


class PhoneNormalizer:
    """
    Normalizes phone numbers to E.164 format.

    Normalization steps:
      1. Strip common formatting characters.
      2. Parse using ``phonenumbers`` with the provided or default region.
      3. Validate the number is valid for that region.
      4. Format to E.164.
    """

    @staticmethod
    def normalize(
        raw: str | None,
        default_region: str = _DEFAULT_REGION,
    ) -> str | None:
        """
        Parse and normalize a single phone number string.

        Returns None if the number cannot be parsed or is invalid.
        """
        if not raw:
            return None

        # Strip common non-digit characters that phonenumbers can't handle
        # when combined with formatting noise (e.g., "Tel: (415) 555-2671")
        cleaned = raw.strip()
        for prefix in ("tel:", "phone:", "ph:", "ph.:", "fax:"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        try:
            parsed = phonenumbers.parse(cleaned, default_region)
        except NumberParseException as exc:
            log.debug("phone_parse_failed", raw=raw, reason=str(exc))
            return None

        if not phonenumbers.is_valid_number(parsed):
            log.debug("phone_invalid", raw=raw, parsed=str(parsed))
            return None

        return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)

    @staticmethod
    def normalize_list(
        phones: list[str],
        default_region: str = _DEFAULT_REGION,
    ) -> list[str]:
        """
        Normalize a list of phone numbers, removing invalids and duplicates.

        Order is preserved; later duplicates are dropped.
        """
        seen: set[str] = set()
        result: list[str] = []
        for raw in phones:
            normalized = PhoneNormalizer.normalize(raw, default_region)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @staticmethod
    def is_valid(raw: str, default_region: str = _DEFAULT_REGION) -> bool:
        """Return True if the phone number is valid for the given region."""
        try:
            parsed = phonenumbers.parse(raw, default_region)
            return phonenumbers.is_valid_number(parsed)
        except NumberParseException:
            return False

    @staticmethod
    def get_country_code(raw: str, default_region: str = _DEFAULT_REGION) -> str | None:
        """Extract the country code (e.g. 'US', 'IN') from a phone number."""
        try:
            parsed = phonenumbers.parse(raw, default_region)
            if phonenumbers.is_valid_number(parsed):
                region = phonenumbers.region_code_for_number(parsed)
                return region
        except NumberParseException:
            pass
        return None
