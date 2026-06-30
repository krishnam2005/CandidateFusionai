"""
normalizers.text_normalizer — General text normalization utilities.

Handles whitespace collapsing, capitalization normalization, and
deduplication of string lists.  Used as a building block by all other
normalizers and by the canonical mapper.
"""

from __future__ import annotations

import re
import unicodedata


class TextNormalizer:
    """
    Stateless utility class for text normalization operations.

    All methods are static — there is no instance state, making this class
    safe to use across threads without synchronization.
    """

    # Compiled patterns for performance (module-level, created once)
    _WHITESPACE_RE: re.Pattern[str] = re.compile(r"\s+")
    _NON_PRINTABLE_RE: re.Pattern[str] = re.compile(r"[^\x20-\x7E\u00A0-\uFFFF]")

    @staticmethod
    def clean(text: str | None) -> str | None:
        """
        Basic cleanup: strip leading/trailing whitespace, collapse internal
        whitespace, and remove non-printable characters.

        Returns None if the input is None or the result is an empty string.
        """
        if text is None:
            return None
        # Normalize unicode (NFC composition)
        text = unicodedata.normalize("NFC", text)
        # Remove non-printable characters
        text = TextNormalizer._NON_PRINTABLE_RE.sub("", text)
        # Collapse whitespace (newlines, tabs, multiple spaces → single space)
        text = TextNormalizer._WHITESPACE_RE.sub(" ", text).strip()
        return text if text else None

    @staticmethod
    def normalize_name(name: str | None) -> str | None:
        """
        Title-case a name, handling edge cases like "van", "de", "O'Brien".

        Examples:
          "john doe"       → "John Doe"
          "MARY O'BRIEN"   → "Mary O'Brien"
          "van der berg"   → "Van Der Berg"  (simplified; full rules are locale-specific)
        """
        cleaned = TextNormalizer.clean(name)
        if not cleaned:
            return None
        return cleaned.title()

    @staticmethod
    def normalize_company(name: str | None) -> str | None:
        """Strip and title-case a company name."""
        cleaned = TextNormalizer.clean(name)
        if not cleaned:
            return None
        # Preserve known acronyms (LLC, Inc, Ltd, etc.)
        known_acronyms = {"llc", "inc", "ltd", "corp", "co", "ag", "gmbh", "sa", "plc"}
        words = cleaned.split()
        result = []
        for word in words:
            if word.lower().rstrip(".") in known_acronyms:
                result.append(word.upper().rstrip(".") + ("." if word.endswith(".") else ""))
            else:
                result.append(word.capitalize())
        return " ".join(result)

    @staticmethod
    def deduplicate(items: list[str]) -> list[str]:
        """Remove duplicates while preserving insertion order (case-insensitive)."""
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(item.strip())
        return result

    @staticmethod
    def split_name(full_name: str) -> tuple[str | None, str | None, str | None]:
        """
        Split a full name into (first, middle, last).

        Handles common formats:
          "John Doe"        → ("John", None, "Doe")
          "John Michael Doe"→ ("John", "Michael", "Doe")
          "Doe, John"       → ("John", None, "Doe")
        """
        if not full_name:
            return None, None, None

        full_name = TextNormalizer.clean(full_name) or ""

        # Handle "Last, First" format
        if "," in full_name:
            parts = [p.strip() for p in full_name.split(",", 1)]
            last = parts[0]
            remaining = parts[1].split() if len(parts) > 1 else []
            first = remaining[0] if remaining else None
            middle = " ".join(remaining[1:]) if len(remaining) > 1 else None
            return first, middle, last

        parts = full_name.split()
        if len(parts) == 1:
            return parts[0], None, None
        elif len(parts) == 2:
            return parts[0], None, parts[1]
        else:
            return parts[0], " ".join(parts[1:-1]), parts[-1]

    @staticmethod
    def truncate(text: str | None, max_length: int = 5000) -> str | None:
        """Truncate text to ``max_length`` characters, appending ellipsis if cut."""
        if not text:
            return text
        if len(text) <= max_length:
            return text
        return text[:max_length].rstrip() + "…"
