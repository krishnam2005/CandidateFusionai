"""Unit tests for normalizer modules."""

from __future__ import annotations

import pytest

from normalizers.date_normalizer import DateNormalizer
from normalizers.email_normalizer import EmailNormalizer
from normalizers.location_normalizer import LocationNormalizer
from normalizers.phone_normalizer import PhoneNormalizer
from normalizers.skill_normalizer import SkillNormalizer
from normalizers.text_normalizer import TextNormalizer
from normalizers.url_normalizer import UrlNormalizer


# ─────────────────────────────────────────────────────────────────────────────
# TextNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestTextNormalizer:
    def test_clean_basic_whitespace(self) -> None:
        assert TextNormalizer.clean("  hello   world  ") == "hello world"

    def test_clean_none_returns_none(self) -> None:
        assert TextNormalizer.clean(None) is None

    def test_clean_empty_returns_none(self) -> None:
        assert TextNormalizer.clean("   ") is None

    def test_clean_collapses_newlines(self) -> None:
        result = TextNormalizer.clean("line1\n\nline2\t\tword")
        assert result == "line1 line2 word"

    def test_normalize_name_title_cases(self) -> None:
        assert TextNormalizer.normalize_name("JOHN DOE") == "John Doe"

    def test_normalize_name_none(self) -> None:
        assert TextNormalizer.normalize_name(None) is None

    def test_deduplicate_preserves_order(self) -> None:
        result = TextNormalizer.deduplicate(["Python", "python", "PYTHON", "JavaScript"])
        assert result == ["Python", "JavaScript"]

    def test_split_name_first_last(self) -> None:
        first, middle, last = TextNormalizer.split_name("John Doe")
        assert first == "John"
        assert middle is None
        assert last == "Doe"

    def test_split_name_last_first_format(self) -> None:
        first, middle, last = TextNormalizer.split_name("Doe, John")
        assert first == "John"
        assert last == "Doe"

    def test_split_name_three_parts(self) -> None:
        first, middle, last = TextNormalizer.split_name("John Michael Doe")
        assert first == "John"
        assert middle == "Michael"
        assert last == "Doe"

    def test_truncate_short_string(self) -> None:
        assert TextNormalizer.truncate("short", 100) == "short"

    def test_truncate_long_string(self) -> None:
        long_str = "a" * 200
        result = TextNormalizer.truncate(long_str, 100)
        assert len(result) <= 101  # 100 + ellipsis char
        assert result.endswith("…")


# ─────────────────────────────────────────────────────────────────────────────
# EmailNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestEmailNormalizer:
    def test_normalize_basic(self) -> None:
        assert EmailNormalizer.normalize("Test@Example.COM") == "test@example.com"

    def test_normalize_strips_whitespace(self) -> None:
        assert EmailNormalizer.normalize("  test@example.com  ") == "test@example.com"

    def test_normalize_plus_address(self) -> None:
        result = EmailNormalizer.normalize("user+tag@example.com")
        assert result == "user@example.com"

    def test_normalize_gmail_plus(self) -> None:
        result = EmailNormalizer.normalize("user+newsletter@gmail.com")
        assert result == "user@gmail.com"

    def test_normalize_invalid_returns_none(self) -> None:
        assert EmailNormalizer.normalize("not-an-email") is None

    def test_normalize_none_returns_none(self) -> None:
        assert EmailNormalizer.normalize(None) is None

    def test_normalize_list_deduplicates(self) -> None:
        emails = ["user@example.com", "USER@example.com", "other@example.com"]
        result = EmailNormalizer.normalize_list(emails)
        assert "user@example.com" in result
        assert "other@example.com" in result
        assert len(result) == 2

    def test_is_valid(self) -> None:
        assert EmailNormalizer.is_valid("test@example.com") is True
        assert EmailNormalizer.is_valid("not-valid") is False


# ─────────────────────────────────────────────────────────────────────────────
# PhoneNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestPhoneNormalizer:
    def test_normalize_us_number(self) -> None:
        result = PhoneNormalizer.normalize("(415) 555-0198")
        assert result == "+14155550198"

    def test_normalize_international(self) -> None:
        result = PhoneNormalizer.normalize("+44 20 7946 0958")
        assert result is not None
        assert result.startswith("+44")

    def test_normalize_e164_passthrough(self) -> None:
        result = PhoneNormalizer.normalize("+14155550198")
        assert result == "+14155550198"

    def test_normalize_none_returns_none(self) -> None:
        assert PhoneNormalizer.normalize(None) is None

    def test_normalize_invalid_returns_none(self) -> None:
        assert PhoneNormalizer.normalize("not-a-phone") is None

    def test_normalize_list_deduplicates(self) -> None:
        phones = ["+14155550198", "(415) 555-0198", "+14085550199"]
        result = PhoneNormalizer.normalize_list(phones)
        assert "+14155550198" in result
        assert "+14085550199" in result
        assert len(result) == 2


# ─────────────────────────────────────────────────────────────────────────────
# DateNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestDateNormalizer:
    def test_parse_iso_date(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("2021-03-15")
        assert result == date(2021, 3, 15)

    def test_parse_month_year(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("Jan 2021")
        assert result == date(2021, 1, 1)

    def test_parse_full_month_name(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("March 2020")
        assert result == date(2020, 3, 1)

    def test_parse_year_only(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("2020")
        assert result == date(2020, 1, 1)

    def test_parse_present_not_end_date(self) -> None:
        result = DateNormalizer.parse("Present")
        assert result is None

    def test_parse_present_as_end_date(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("Present", is_end_date=True)
        assert result == date.today()

    def test_parse_none_returns_none(self) -> None:
        assert DateNormalizer.parse(None) is None

    def test_parse_invalid_returns_none(self) -> None:
        assert DateNormalizer.parse("not-a-date") is None

    def test_parse_range(self) -> None:
        start, end, is_current = DateNormalizer.parse_range("Jan 2018 – Mar 2022")
        from datetime import date
        assert start == date(2018, 1, 1)
        assert end == date(2022, 3, 1)
        assert is_current is False

    def test_parse_range_present(self) -> None:
        start, end, is_current = DateNormalizer.parse_range("Jan 2021 - Present")
        assert is_current is True

    def test_quarter_pattern(self) -> None:
        from datetime import date
        result = DateNormalizer.parse("Q3 2019")
        assert result == date(2019, 7, 1)


# ─────────────────────────────────────────────────────────────────────────────
# SkillNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillNormalizer:
    def test_normalize_exact_alias(self) -> None:
        assert SkillNormalizer.normalize("python3") == "Python"

    def test_normalize_reactjs(self) -> None:
        assert SkillNormalizer.normalize("reactjs") == "React"

    def test_normalize_react_js(self) -> None:
        assert SkillNormalizer.normalize("react.js") == "React"

    def test_normalize_postgres(self) -> None:
        assert SkillNormalizer.normalize("postgres") == "PostgreSQL"

    def test_normalize_k8s(self) -> None:
        assert SkillNormalizer.normalize("k8s") == "Kubernetes"

    def test_normalize_unknown_skill_titlecases(self) -> None:
        result = SkillNormalizer.normalize("my custom framework")
        assert result[0].isupper()

    def test_normalize_list_deduplicates(self) -> None:
        skills = ["Python", "python3", "python", "JavaScript"]
        result = SkillNormalizer.normalize_list(skills)
        assert result.count("Python") == 1

    def test_normalize_empty(self) -> None:
        assert SkillNormalizer.normalize("") == ""

    def test_get_aliases(self) -> None:
        aliases = SkillNormalizer.get_aliases("Python")
        assert "python3" in aliases


# ─────────────────────────────────────────────────────────────────────────────
# LocationNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestLocationNormalizer:
    def test_parse_city_state(self) -> None:
        loc = LocationNormalizer.normalize("San Francisco, CA")
        assert loc is not None
        assert loc.city == "San Francisco"

    def test_parse_city_state_country(self) -> None:
        loc = LocationNormalizer.normalize("New York, NY, USA")
        assert loc is not None
        assert loc.city == "New York"
        assert loc.country_code == "US"

    def test_parse_remote(self) -> None:
        loc = LocationNormalizer.normalize("Remote")
        assert loc is not None
        assert loc.city == "Remote"

    def test_parse_none_returns_none(self) -> None:
        assert LocationNormalizer.normalize(None) is None

    def test_parse_empty_returns_none(self) -> None:
        assert LocationNormalizer.normalize("") is None

    def test_merge_fills_missing_fields(self) -> None:
        a = LocationNormalizer.normalize("San Francisco")
        b = LocationNormalizer.normalize("San Francisco, CA, USA")
        merged = LocationNormalizer.merge(a, b)
        assert merged is not None
        assert merged.state is not None or merged.country is not None


# ─────────────────────────────────────────────────────────────────────────────
# UrlNormalizer
# ─────────────────────────────────────────────────────────────────────────────


class TestUrlNormalizer:
    def test_normalize_adds_https(self) -> None:
        result = UrlNormalizer.normalize("linkedin.com/in/janesmith")
        assert result is not None
        assert result.startswith("https://")

    def test_normalize_strips_trailing_slash(self) -> None:
        result = UrlNormalizer.normalize("https://github.com/user/")
        assert result is not None
        assert not result.endswith("/")

    def test_normalize_lowercases_host(self) -> None:
        result = UrlNormalizer.normalize("https://GitHub.COM/user")
        assert result is not None
        assert "github.com" in result

    def test_normalize_none_returns_none(self) -> None:
        assert UrlNormalizer.normalize(None) is None

    def test_detect_platform_github(self) -> None:
        assert UrlNormalizer.detect_platform("https://github.com/user") == "github"

    def test_detect_platform_linkedin(self) -> None:
        assert UrlNormalizer.detect_platform("https://linkedin.com/in/user") == "linkedin"

    def test_detect_platform_unknown(self) -> None:
        assert UrlNormalizer.detect_platform("https://mysite.com") == "other"

    def test_extract_github_username(self) -> None:
        username = UrlNormalizer.extract_github_username("https://github.com/janesmith")
        assert username == "janesmith"
