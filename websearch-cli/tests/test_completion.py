from __future__ import annotations

from commands.completion import (
    CountryParamType,
    HackerNewsTagsParamType,
    LanguageParamType,
    SourceParamType,
)


def test_language_completion():
    items = LanguageParamType().shell_complete(None, None, "en")
    assert [c.value for c in items] == ["en"]


def test_country_completion_case_insensitive():
    items = CountryParamType().shell_complete(None, None, "us")
    assert [c.value for c in items] == ["US"]


def test_hn_tags_completion():
    items = HackerNewsTagsParamType().shell_complete(None, None, "st")
    assert [c.value for c in items] == ["story"]
    items = HackerNewsTagsParamType().shell_complete(None, None, "show")
    assert [c.value for c in items] == ["show_hn"]


def test_source_completion_includes_providers_and_all():
    items = SourceParamType().shell_complete(None, None, "")
    values = [c.value for c in items]
    assert "all" in values
    assert {"google_news", "reddit", "hacker_news"} <= set(values)
