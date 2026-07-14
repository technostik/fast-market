from __future__ import annotations

from pathlib import Path

import click
from click.shell_completion import CompletionItem

from common.core.config import load_tool_config
from common.core.registry import discover_plugins

_TOOL_ROOT = Path(__file__).resolve().parents[1]

_LANGUAGE_CODES = ["fr", "en", "es", "de", "it", "pt", "nl", "ru", "ja", "zh", "ar"]
_COUNTRY_CODES = ["FR", "US", "ES", "DE", "IT", "PT", "NL", "RU", "JP", "CN", "GB", "CA", "AU"]
_HN_TAGS = ["story", "comment", "poll", "job", "show_hn", "ask_hn"]


class SourceParamType(click.ParamType):
    """Completes provider names from discovered plugin manifests (plus "all")."""

    name = "source"

    def shell_complete(self, ctx, param, incomplete):
        try:
            config = load_tool_config("websearch")
            manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
            names = list(manifests.keys()) + ["all"]
        except Exception:
            names = ["all"]
        return [
            CompletionItem(n, help="search provider")
            for n in names
            if incomplete.lower() in n.lower()
        ]


class LanguageParamType(click.ParamType):
    """Completes Google News language (hl) codes."""

    name = "language"

    def shell_complete(self, ctx, param, incomplete):
        return [
            CompletionItem(c) for c in _LANGUAGE_CODES if c.startswith(incomplete.lower())
        ]


class CountryParamType(click.ParamType):
    """Completes Google News geolocation (gl) codes."""

    name = "country"

    def shell_complete(self, ctx, param, incomplete):
        return [
            CompletionItem(c) for c in _COUNTRY_CODES if c.startswith(incomplete.upper())
        ]


class HackerNewsTagsParamType(click.ParamType):
    """Completes Hacker News tag filters."""

    name = "hn_tags"

    def shell_complete(self, ctx, param, incomplete):
        return [
            CompletionItem(t) for t in _HN_TAGS if t.startswith(incomplete.lower())
        ]
