"""
normalizers.location_normalizer — Location string parsing and normalization.

Attempts to parse free-text location strings into structured Location objects
(city, state, country, country_code).

Design approach:
  - Uses a curated country/state mapping for common HR data patterns.
  - Falls back to storing the raw string rather than failing.
  - Does NOT call any geocoding API to avoid external dependencies, latency,
    and cost.  A production system could plug in a geocoding service here
    behind an interface.
"""

from __future__ import annotations

import re

from models.candidate import Location
from utils.logging import get_logger

log = get_logger(__name__)

# ── Country name → ISO 3166-1 alpha-2 code ───────────────────────────────────
_COUNTRY_TO_CODE: dict[str, str] = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "u.s.a.": "US",
    "us": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "india": "IN",
    "germany": "DE",
    "france": "FR",
    "australia": "AU",
    "netherlands": "NL",
    "singapore": "SG",
    "japan": "JP",
    "china": "CN",
    "brazil": "BR",
    "mexico": "MX",
    "spain": "ES",
    "italy": "IT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "switzerland": "CH",
    "new zealand": "NZ",
    "ireland": "IE",
    "portugal": "PT",
    "poland": "PL",
    "ukraine": "UA",
    "russia": "RU",
    "south korea": "KR",
    "korea": "KR",
    "taiwan": "TW",
    "israel": "IL",
    "uae": "AE",
    "united arab emirates": "AE",
    "south africa": "ZA",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "indonesia": "ID",
    "malaysia": "MY",
    "philippines": "PH",
    "vietnam": "VN",
    "thailand": "TH",
    "pakistan": "PK",
    "bangladesh": "BD",
    "nigeria": "NG",
    "kenya": "KE",
}

# US state abbreviations
_US_STATE_ABBREV: dict[str, str] = {
    "al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas",
    "ca": "California", "co": "Colorado", "ct": "Connecticut", "de": "Delaware",
    "fl": "Florida", "ga": "Georgia", "hi": "Hawaii", "id": "Idaho",
    "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
    "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland",
    "ma": "Massachusetts", "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi",
    "mo": "Missouri", "mt": "Montana", "ne": "Nebraska", "nv": "Nevada",
    "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico", "ny": "New York",
    "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
    "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina",
    "sd": "South Dakota", "tn": "Tennessee", "tx": "Texas", "ut": "Utah",
    "vt": "Vermont", "va": "Virginia", "wa": "Washington", "wv": "West Virginia",
    "wi": "Wisconsin", "wy": "Wyoming", "dc": "District of Columbia",
    "remote": "Remote",
}

# Reverse: full state name → abbrev
_US_STATE_NAME_TO_ABBREV: dict[str, str] = {v.lower(): k.upper() for k, v in _US_STATE_ABBREV.items()}


class LocationNormalizer:
    """
    Parses free-text location strings into structured Location objects.

    Parsing heuristic (comma-delimited):
      "City, State, Country" → city, state, country
      "City, State" → city, state (country inferred as US if state is recognized)
      "City" → city only
      "Remote" → special-cased

    This is intentionally heuristic and will not cover every edge case.
    For production accuracy, back this with a geocoding service.
    """

    @staticmethod
    def normalize(raw: str | None) -> Location | None:
        """Parse a raw location string into a Location model."""
        if not raw:
            return None

        cleaned = raw.strip()
        if not cleaned:
            return None

        lower = cleaned.lower()

        # Special: Remote
        if lower in {"remote", "fully remote", "work from home", "wfh", "anywhere"}:
            return Location(city="Remote", raw=cleaned)

        # Split on comma
        parts = [p.strip() for p in cleaned.split(",")]

        city: str | None = None
        state: str | None = None
        country: str | None = None
        country_code: str | None = None

        if len(parts) == 1:
            city = parts[0]
        elif len(parts) == 2:
            city = parts[0]
            second = parts[1].strip()
            second_lower = second.lower()

            # Check if second part is a known country
            code = _COUNTRY_TO_CODE.get(second_lower)
            if code:
                country = second
                country_code = code
            else:
                # Assume it's a US state
                state = _US_STATE_ABBREV.get(second_lower, second)
                if second_lower in _US_STATE_NAME_TO_ABBREV or second_lower in _US_STATE_ABBREV:
                    country = "United States"
                    country_code = "US"
        elif len(parts) >= 3:
            city = parts[0]
            state = parts[1]
            country_raw = parts[2]
            country_lower = country_raw.lower()
            code = _COUNTRY_TO_CODE.get(country_lower)
            country = country_raw
            country_code = code

        return Location(
            city=city,
            state=state,
            country=country,
            country_code=country_code,
            raw=cleaned,
        )

    @staticmethod
    def merge(a: Location | None, b: Location | None) -> Location | None:
        """
        Merge two Location objects, preferring the more complete one.

        Returns None if both are None.
        """
        if a is None:
            return b
        if b is None:
            return a

        # Build merged by preferring non-None values from both
        return Location(
            city=a.city or b.city,
            state=a.state or b.state,
            country=a.country or b.country,
            country_code=a.country_code or b.country_code,
            postal_code=a.postal_code or b.postal_code,
            raw=a.raw or b.raw,
        )
