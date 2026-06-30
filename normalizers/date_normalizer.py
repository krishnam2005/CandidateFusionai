"""
normalizers.date_normalizer — Flexible date string parsing and normalization.

Uses ``python-dateutil`` for robust parsing of ambiguous or locale-specific
date strings, supplemented by hand-rolled parsing for common resume patterns
like "Jan 2020", "Q3 2019", "Present", etc.

Design rationale for dateutil:
  - Handles hundreds of date formats automatically without an explicit format list.
  - Configurable ``dayfirst`` and ``yearfirst`` flags for regional formats.
  - No external API calls.
  - Lightweight and widely trusted in the Python ecosystem.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError

from utils.logging import get_logger

log = get_logger(__name__)

# Patterns for "present", "current", "now" — map to today's date
_CURRENT_INDICATORS = frozenset(
    {"present", "current", "now", "ongoing", "today", "till date", "till now", "to date"}
)

# Month abbreviation → number
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

# Pattern: "Jan 2020", "January 2020"
_MONTH_YEAR_RE = re.compile(
    r"^(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})$",
    re.IGNORECASE,
)

# Pattern: "2020" (year only)
_YEAR_ONLY_RE = re.compile(r"^(?P<year>\d{4})$")

# Pattern: "Q1 2020", "Q3 2019"
_QUARTER_RE = re.compile(r"^Q(?P<quarter>[1-4])\s+(?P<year>\d{4})$", re.IGNORECASE)

# Quarter → starting month
_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}


class DateNormalizer:
    """
    Parses and normalizes date strings from diverse resume/HR sources.

    Returns ``datetime.date`` objects for downstream use, or None on failure.
    All parsing is fault-tolerant — exceptions are logged and None is returned
    rather than propagating.
    """

    @staticmethod
    def parse(raw: str | None, *, is_end_date: bool = False) -> date | None:
        """
        Parse a raw date string into a ``datetime.date``.

        Parameters
        ----------
        raw:
            The input date string to parse.
        is_end_date:
            When True and the string is a "current" indicator, returns
            ``date.today()`` rather than None (so duration computations work).
        """
        if not raw:
            return None

        stripped = raw.strip()
        lower = stripped.lower()

        # ── Current / Present indicators ────────────────────────────────────
        if lower in _CURRENT_INDICATORS:
            return date.today() if is_end_date else None

        # ── Quarter pattern ──────────────────────────────────────────────────
        q_match = _QUARTER_RE.match(stripped)
        if q_match:
            quarter = int(q_match.group("quarter"))
            year = int(q_match.group("year"))
            month = _QUARTER_START_MONTH[quarter]
            return date(year, month, 1)

        # ── Month Year pattern ───────────────────────────────────────────────
        my_match = _MONTH_YEAR_RE.match(stripped)
        if my_match:
            month_str = my_match.group("month").lower()[:3]
            year = int(my_match.group("year"))
            month = _MONTH_MAP.get(month_str)
            if month:
                return date(year, month, 1)

        # ── Year-only pattern ────────────────────────────────────────────────
        y_match = _YEAR_ONLY_RE.match(stripped)
        if y_match:
            year = int(y_match.group("year"))
            if 1950 <= year <= date.today().year + 5:
                return date(year, 1, 1)

        # ── General dateutil parsing ─────────────────────────────────────────
        try:
            parsed = dateutil_parser.parse(
                stripped,
                dayfirst=False,  # MM/DD/YYYY is dominant in US recruiting contexts
                yearfirst=False,
                default=datetime(date.today().year, 1, 1),
            )
            return parsed.date()
        except (ParserError, OverflowError, ValueError) as exc:
            log.debug("date_parse_failed", raw=raw, reason=str(exc))
            return None

    @staticmethod
    def parse_range(
        raw: str | None,
    ) -> tuple[date | None, date | None, bool]:
        """
        Parse a date range string like "Jan 2018 – Mar 2022" or "2018 - Present".

        Returns (start_date, end_date, is_current).
        is_current is True when the end of the range is a present indicator.
        """
        if not raw:
            return None, None, False

        # Common range separators
        for separator in [" – ", " - ", " to ", "–", "-", "/", "~"]:
            if separator in raw:
                parts = raw.split(separator, 1)
                start_raw = parts[0].strip()
                end_raw = parts[1].strip() if len(parts) > 1 else ""

                is_current = end_raw.lower() in _CURRENT_INDICATORS
                start_date = DateNormalizer.parse(start_raw)
                end_date = (
                    date.today()
                    if is_current
                    else DateNormalizer.parse(end_raw, is_end_date=True)
                )
                return start_date, end_date, is_current

        # Single date (no separator found)
        parsed = DateNormalizer.parse(raw)
        return parsed, None, False

    @staticmethod
    def to_iso(d: date | None) -> str | None:
        """Format a date as ISO 8601 string ("YYYY-MM-DD"), or None."""
        return d.isoformat() if d else None
