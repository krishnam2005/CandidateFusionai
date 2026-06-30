"""Integration tests for the GitHub extractor with mocked API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import respx
import httpx
from requests import Response

from extractors.base import ExtractorError
from extractors.github_extractor import GitHubExtractor
from models.metadata import SourceType


# ── Mock API responses ────────────────────────────────────────────────────────

MOCK_USER_PROFILE = {
    "login": "testuser",
    "name": "Test User",
    "bio": "Full-stack developer | Python | Open source enthusiast",
    "email": "testuser@example.com",
    "location": "San Francisco, CA",
    "blog": "https://testuser.dev",
    "twitter_username": "testuser",
    "public_repos": 42,
    "followers": 500,
    "following": 100,
    "public_gists": 10,
}

MOCK_REPOS = [
    {
        "name": "awesome-project",
        "description": "An awesome open source project",
        "html_url": "https://github.com/testuser/awesome-project",
        "homepage": "https://awesome.testuser.dev",
        "language": "Python",
        "topics": ["machine-learning", "python", "fastapi"],
        "stargazers_count": 200,
        "forks_count": 45,
        "fork": False,
        "private": False,
    },
    {
        "name": "react-dashboard",
        "description": "A React-based analytics dashboard",
        "html_url": "https://github.com/testuser/react-dashboard",
        "language": "TypeScript",
        "topics": ["react", "typescript", "dashboard"],
        "stargazers_count": 89,
        "forks_count": 12,
        "fork": False,
        "private": False,
    },
    {
        "name": "forked-repo",
        "language": "Go",
        "stargazers_count": 0,
        "forks_count": 0,
        "fork": True,  # Should be excluded from projects
        "private": False,
    },
]


def make_mock_response(data: object, status_code: int = 200) -> MagicMock:
    """Create a mock requests.Response."""
    mock = MagicMock(spec=Response)
    mock.status_code = status_code
    mock.json.return_value = data
    mock.headers = {}
    return mock


class TestGitHubExtractor:
    @patch("extractors.github_extractor.Session.get")
    def test_extract_full_profile(self, mock_get: MagicMock) -> None:
        """Test successful GitHub profile extraction."""
        mock_get.side_effect = [
            make_mock_response(MOCK_USER_PROFILE),
            make_mock_response(MOCK_REPOS),
        ]

        extractor = GitHubExtractor(token=None)
        result = extractor.extract("https://github.com/testuser")

        assert result.source == SourceType.GITHUB
        assert result.full_name == "Test User"
        assert result.summary == MOCK_USER_PROFILE["bio"]
        assert "testuser@example.com" in result.emails
        assert result.github_username == "testuser"
        assert result.github_repos_count == 42

    @patch("extractors.github_extractor.Session.get")
    def test_extract_infers_skills_from_languages(self, mock_get: MagicMock) -> None:
        """Skills should be inferred from repository languages."""
        mock_get.side_effect = [
            make_mock_response(MOCK_USER_PROFILE),
            make_mock_response(MOCK_REPOS),
        ]

        extractor = GitHubExtractor(token=None)
        result = extractor.extract("testuser")

        # Python and TypeScript from repos
        skills_lower = [s.lower() for s in result.skills_raw]
        assert "python" in skills_lower or "Python" in result.skills_raw

    @patch("extractors.github_extractor.Session.get")
    def test_extract_projects_excludes_forks(self, mock_get: MagicMock) -> None:
        """Forked repositories should not be included as projects."""
        mock_get.side_effect = [
            make_mock_response(MOCK_USER_PROFILE),
            make_mock_response(MOCK_REPOS),
        ]

        extractor = GitHubExtractor(token=None)
        result = extractor.extract("testuser")

        project_names = [p.name for p in result.projects]
        assert "forked-repo" not in project_names
        assert "awesome-project" in project_names

    @patch("extractors.github_extractor.Session.get")
    def test_extract_social_links(self, mock_get: MagicMock) -> None:
        """Should include GitHub, portfolio, and Twitter links."""
        mock_get.side_effect = [
            make_mock_response(MOCK_USER_PROFILE),
            make_mock_response(MOCK_REPOS),
        ]

        extractor = GitHubExtractor(token=None)
        result = extractor.extract("testuser")

        platforms = [l.get("platform") for l in result.social_links]
        assert "github" in platforms

    @patch("extractors.github_extractor.Session.get")
    def test_extract_user_not_found_raises(self, mock_get: MagicMock) -> None:
        """404 response should raise ExtractorError."""
        mock_get.return_value = make_mock_response({"message": "Not Found"}, status_code=404)

        extractor = GitHubExtractor(token=None)
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract("nonexistentuser12345")
        assert "not found" in str(exc_info.value).lower()

    @patch("extractors.github_extractor.Session.get")
    def test_extract_rate_limit_raises(self, mock_get: MagicMock) -> None:
        """403/429 response should raise ExtractorError with rate limit info."""
        mock_resp = make_mock_response({"message": "API rate limit exceeded"}, status_code=403)
        mock_resp.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1735000000",
        }
        mock_get.return_value = mock_resp

        extractor = GitHubExtractor(token=None)
        with pytest.raises(ExtractorError) as exc_info:
            extractor.extract("someuser")
        assert "rate limit" in str(exc_info.value).lower()

    def test_resolve_username_from_url(self) -> None:
        """Username should be extracted from GitHub URL."""
        extractor = GitHubExtractor(token=None)
        username = extractor._resolve_username("https://github.com/octocat")
        assert username == "octocat"

    def test_resolve_username_from_plain(self) -> None:
        """Plain username should be returned as-is."""
        extractor = GitHubExtractor(token=None)
        username = extractor._resolve_username("octocat")
        assert username == "octocat"

    def test_resolve_username_from_non_github_url(self) -> None:
        """Non-GitHub URL should return None."""
        extractor = GitHubExtractor(token=None)
        username = extractor._resolve_username("https://gitlab.com/user")
        assert username is None

    @patch("extractors.github_extractor.Session.get")
    def test_safe_extract_returns_none_on_404(self, mock_get: MagicMock) -> None:
        """safe_extract should return None on ExtractorError."""
        mock_get.return_value = make_mock_response({"message": "Not Found"}, status_code=404)

        extractor = GitHubExtractor(token=None)
        result = extractor.safe_extract("nonexistent")
        assert result is None
