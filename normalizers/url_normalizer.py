"""
normalizers.url_normalizer — URL normalization and validation.

Ensures all URLs are fully qualified (have a scheme), removes unnecessary
query params/fragments, and normalises trailing slashes.

We chose to NOT use a heavy library like ``furl`` for this because the
normalization requirements are lightweight and adding another dependency
for simple URL cleaning is overkill.
"""

from __future__ import annotations

import re
from urllib.parse import ParseResult, urlencode, urlparse, urlunparse

from utils.logging import get_logger

log = get_logger(__name__)

# Platforms for social URL detection
_PLATFORM_PATTERNS: dict[str, re.Pattern[str]] = {
    "linkedin": re.compile(r"linkedin\.com/in/", re.IGNORECASE),
    "github": re.compile(r"github\.com/", re.IGNORECASE),
    "twitter": re.compile(r"(?:twitter|x)\.com/", re.IGNORECASE),
    "stackoverflow": re.compile(r"stackoverflow\.com/users/", re.IGNORECASE),
}


class UrlNormalizer:
    """
    Normalizes and validates URLs.

    Normalization steps:
      1. Strip surrounding whitespace.
      2. Add ``https://`` scheme if missing.
      3. Lowercase the host.
      4. Remove default ports (80, 443).
      5. Remove ``www.`` prefix for known social platforms.
      6. Strip trailing slashes from paths (except root).
    """

    @staticmethod
    def normalize(raw: str | None) -> str | None:
        """
        Normalize a single URL string.

        Returns None if the URL is empty or unparseable.
        """
        if not raw:
            return None

        url = raw.strip()

        # Add scheme if missing
        if not url.startswith(("http://", "https://", "ftp://")):
            url = f"https://{url}"

        try:
            parsed: ParseResult = urlparse(url)
        except ValueError as exc:
            log.debug("url_parse_failed", raw=raw, reason=str(exc))
            return None

        if not parsed.netloc:
            log.debug("url_missing_netloc", raw=raw)
            return None

        # Lowercase host
        host = parsed.hostname or ""
        port = parsed.port

        # Strip default ports
        netloc = host
        if port and not (
            (parsed.scheme == "https" and port == 443)
            or (parsed.scheme == "http" and port == 80)
        ):
            netloc = f"{host}:{port}"

        # Remove trailing slash from path (unless root)
        path = parsed.path.rstrip("/") or "/"

        normalized = urlunparse((
            parsed.scheme,
            netloc,
            path,
            parsed.params,
            "",   # Strip query string for social/profile URLs
            "",   # Strip fragment
        ))

        return normalized

    @staticmethod
    def normalize_list(urls: list[str]) -> list[str]:
        """Normalize a list of URLs, removing invalids and duplicates."""
        seen: set[str] = set()
        result: list[str] = []
        for raw in urls:
            normalized = UrlNormalizer.normalize(raw)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    @staticmethod
    def detect_platform(url: str) -> str:
        """
        Detect the social platform of a URL.

        Returns the platform name (e.g. "github", "linkedin") or "other".
        """
        for platform, pattern in _PLATFORM_PATTERNS.items():
            if pattern.search(url):
                return platform
        return "other"

    @staticmethod
    def extract_github_username(url: str) -> str | None:
        """Extract the GitHub username from a GitHub profile URL."""
        parsed = urlparse(url)
        if "github.com" not in (parsed.hostname or ""):
            return None
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts:
            return path_parts[0]
        return None
