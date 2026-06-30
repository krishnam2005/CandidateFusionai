"""
extractors.github_extractor — GitHub profile data extractor via REST API.

Fetches public profile data from the GitHub REST API v3, including:
  - User profile (name, bio, location, blog, email)
  - Public repositories (for skills inference and project listing)
  - Pinned repos (if available — requires GraphQL, so we use top repos by stars)

API endpoints used:
  - GET /users/{username}           — profile
  - GET /users/{username}/repos     — repositories

Rate limiting:
  - Unauthenticated: 60 req/hr
  - Authenticated (PAT): 5000 req/hr
  → Always use a token in production (configured in .env)

Error handling:
  - 404: User not found → ExtractorError with descriptive message
  - 403/429: Rate limited → ExtractorError with Retry-After info
  - Timeout: Configurable, retried with exponential backoff
  - Network errors: Retried with exponential backoff

Why requests over httpx?
  - Simpler synchronous API for this use case.
  - Battle-tested in production at scale.
  - httpx is preferred for async contexts; this extractor is sync.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from extractors.base import BaseExtractor, ExtractorError
from models.extracted import ExtractedCandidate, RawProject
from models.metadata import SourceType
from normalizers.skill_normalizer import SkillNormalizer
from utils.logging import get_logger
from utils.timer import timed

log = get_logger(__name__)

# Languages that map well to skills
_SKIP_LANGUAGES = frozenset({"Makefile", "Dockerfile", "Shell", "Batchfile", "CMake"})

# Max repos to fetch for language/skill inference
_MAX_REPOS = 30
# Max repos to include as projects in the profile
_MAX_PROJECTS = 10


class GitHubExtractor(BaseExtractor):
    """
    Extracts candidate data from a GitHub profile URL.

    Accepts both:
      - Full profile URL: "https://github.com/octocat"
      - Username only:    "octocat"
    """

    source_type = SourceType.GITHUB

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = self._build_session(max_retries)

    def _build_session(self, max_retries: int) -> Session:
        """Configure a requests Session with retry logic and auth headers."""
        session = Session()

        headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CandidateFusion-AI/1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        session.headers.update(headers)

        # Retry on transient errors (408, 429, 500, 502, 503, 504)
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1.5,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    def extract(self, source: str | Path) -> ExtractedCandidate:
        """
        Extract candidate data from a GitHub profile URL or username.

        Parameters
        ----------
        source:
            GitHub profile URL (e.g. "https://github.com/octocat")
            or plain username (e.g. "octocat").

        Raises
        ------
        ExtractorError
            On API errors, rate limits, timeouts, or user-not-found.
        """
        username = self._resolve_username(str(source))

        if not username:
            raise ExtractorError(
                f"Cannot extract GitHub username from: {source}",
                source=self.source_type,
            )

        with timed("github_extraction", username=username):
            return self._extract_user(username)

    def _resolve_username(self, source: str) -> str | None:
        """Extract a username from a URL or return the raw string if it's a username."""
        source = source.strip()
        if source.startswith(("http://", "https://")):
            parsed = urlparse(source)
            if "github.com" not in (parsed.hostname or ""):
                return None
            parts = [p for p in parsed.path.split("/") if p]
            return parts[0] if parts else None
        # Assume it's a plain username
        return source if source and "/" not in source else None

    def _extract_user(self, username: str) -> ExtractedCandidate:
        log.info("github_extraction_start", username=username)

        # ── Fetch profile ─────────────────────────────────────────────────
        profile_data = self._api_get(f"/users/{username}")

        # ── Fetch repositories ────────────────────────────────────────────
        repos_data = self._api_get(
            f"/users/{username}/repos",
            params={
                "sort": "pushed",
                "direction": "desc",
                "per_page": _MAX_REPOS,
                "type": "owner",
            },
        )
        if not isinstance(repos_data, list):
            repos_data = []

        # ── Parse skills from repo languages ──────────────────────────────
        skills_raw = self._infer_skills_from_repos(repos_data)

        # ── Parse projects from top repos ─────────────────────────────────
        projects = self._parse_projects(repos_data)

        # ── Parse social links ────────────────────────────────────────────
        social_links: list[dict[str, Any]] = [
            {"platform": "github", "url": f"https://github.com/{username}"}
        ]
        blog = profile_data.get("blog", "")
        if blog:
            if not blog.startswith(("http://", "https://")):
                blog = f"https://{blog}"
            social_links.append({"platform": "portfolio", "url": blog})

        twitter_username = profile_data.get("twitter_username")
        if twitter_username:
            social_links.append({
                "platform": "twitter",
                "url": f"https://twitter.com/{twitter_username}",
            })

        emails: list[str] = []
        email = profile_data.get("email")
        if email:
            emails.append(email)

        extracted = ExtractedCandidate(
            source=self.source_type,
            raw_path=f"https://github.com/{username}",
            full_name=profile_data.get("name"),
            emails=emails,
            location_raw=profile_data.get("location"),
            summary=profile_data.get("bio"),
            skills_raw=skills_raw,
            projects=projects,
            social_links=social_links,
            github_username=username,
            github_repos_count=profile_data.get("public_repos", 0),
            github_followers=profile_data.get("followers", 0),
            github_following=profile_data.get("following", 0),
            github_public_gists=profile_data.get("public_gists", 0),
        )

        log.info(
            "github_extraction_complete",
            username=username,
            skills=len(skills_raw),
            repos=len(repos_data),
            projects=len(projects),
        )

        return extracted

    def _api_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Make a GitHub API GET request with error handling.

        Raises ExtractorError on HTTP errors.
        """
        url = f"{self._base_url}{endpoint}"
        log.debug("github_api_request", url=url, params=params)

        try:
            response: Response = self._session.get(
                url,
                params=params,
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise ExtractorError(
                f"GitHub API timeout after {self._timeout}s for {url}",
                source=self.source_type,
                cause=exc,
            ) from exc
        except requests.ConnectionError as exc:
            raise ExtractorError(
                f"GitHub API connection error for {url}: {exc}",
                source=self.source_type,
                cause=exc,
            ) from exc

        self._handle_response_errors(response, url)

        try:
            return response.json()
        except ValueError as exc:
            raise ExtractorError(
                f"Invalid JSON response from GitHub API: {url}",
                source=self.source_type,
                cause=exc,
            ) from exc

    def _handle_response_errors(self, response: Response, url: str) -> None:
        """Translate HTTP error codes to ExtractorError with helpful messages."""
        if response.status_code == 200:
            return

        if response.status_code == 404:
            raise ExtractorError(
                f"GitHub user not found: {url}",
                source=self.source_type,
            )

        if response.status_code in (403, 429):
            retry_after = response.headers.get("Retry-After", "unknown")
            rate_limit_remaining = response.headers.get("X-RateLimit-Remaining", "?")
            rate_limit_reset = response.headers.get("X-RateLimit-Reset", "?")
            raise ExtractorError(
                f"GitHub API rate limit exceeded. "
                f"Remaining: {rate_limit_remaining}, "
                f"Reset at: {rate_limit_reset}, "
                f"Retry-After: {retry_after}s. "
                f"Set GITHUB_TOKEN in .env to increase rate limit to 5000/hr.",
                source=self.source_type,
            )

        if response.status_code >= 500:
            raise ExtractorError(
                f"GitHub API server error {response.status_code} for {url}",
                source=self.source_type,
            )

        raise ExtractorError(
            f"GitHub API returned unexpected status {response.status_code} for {url}",
            source=self.source_type,
        )

    def _infer_skills_from_repos(self, repos: list[dict[str, Any]]) -> list[str]:
        """
        Infer skills from repository primary languages.

        Collects all primary languages from repos and normalizes them
        through the SkillNormalizer.
        """
        language_counts: dict[str, int] = {}
        for repo in repos:
            lang = repo.get("language")
            if lang and lang not in _SKIP_LANGUAGES:
                language_counts[lang] = language_counts.get(lang, 0) + 1

        # Sort by frequency descending
        sorted_langs = sorted(language_counts, key=lambda l: language_counts[l], reverse=True)
        return SkillNormalizer.normalize_list(sorted_langs)

    def _parse_projects(self, repos: list[dict[str, Any]]) -> list[RawProject]:
        """Convert top GitHub repos to RawProject objects."""
        # Sort by stars descending, take top N
        sorted_repos = sorted(
            [r for r in repos if not r.get("fork", False)],
            key=lambda r: r.get("stargazers_count", 0),
            reverse=True,
        )[:_MAX_PROJECTS]

        projects: list[RawProject] = []
        for repo in sorted_repos:
            description = repo.get("description") or ""
            topics = repo.get("topics") or []
            technologies = [repo.get("language")] if repo.get("language") else []
            technologies.extend(topics[:5])  # Include topics as technologies
            technologies = [t for t in technologies if t]

            projects.append(
                RawProject(
                    name=repo.get("name", ""),
                    description=description[:500] if description else None,
                    url=repo.get("homepage") or None,
                    repository_url=repo.get("html_url"),
                    technologies=technologies,
                    is_open_source=not repo.get("private", False),
                    stars=repo.get("stargazers_count", 0),
                    forks=repo.get("forks_count", 0),
                )
            )

        return projects
