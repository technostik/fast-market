from __future__ import annotations

import json

from commands.helpers import build_providers
from plugins.google_news.plugin import GoogleNewsPlugin
from plugins.hacker_news.plugin import HackerNewsPlugin
from plugins.reddit.plugin import RedditPlugin
from tests.conftest import _main_with_reload
from tests.fakes import FakeTransport

_CONFIG = {
    "language": "fr",
    "limit": 10,
    "google_news": {"hl": "fr", "gl": "FR"},
    "reddit": {"user_agent": "test", "client_id": "", "client_secret": ""},
    "hacker_news": {"tags": "story"},
}


def _fake_providers(config):
    return {
        "google_news": GoogleNewsPlugin(config, transport=FakeTransport()),
        "reddit": RedditPlugin(config, transport=FakeTransport()),
        "hacker_news": HackerNewsPlugin(config, transport=FakeTransport()),
    }


def test_search_all_sources(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers", lambda config, tool_root=None: _fake_providers(config)
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "cats", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 6
    assert {item["source"] for item in data} == {"google_news", "reddit", "hacker_news"}
    assert all({"url", "title", "description", "source"} <= set(item) for item in data)


def test_bare_invocation_routes_to_search(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers", lambda config, tool_root=None: _fake_providers(config)
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["cats", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 6


def test_search_single_source(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers", lambda config, tool_root=None: _fake_providers(config)
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "cats", "--source", "reddit", "-F", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 2
    assert all(item["source"] == "reddit" for item in data)


def test_search_text_format(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers", lambda config, tool_root=None: _fake_providers(config)
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "cats", "--source", "hacker_news", "-F", "text"])
    assert result.exit_code == 0, result.output
    assert "hacker_news" in result.output


class _FailingPlugin:
    name = "failer"

    def search(self, query, limit, **kwargs):
        raise RuntimeError("boom")


def _fake_providers_with_failure(config):
    providers = _fake_providers(config)
    providers["failer"] = _FailingPlugin()
    return providers


def test_provider_failure_is_non_fatal(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers",
        lambda config, tool_root=None: _fake_providers_with_failure(config),
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "cats", "--format", "json"])
    assert result.exit_code == 0, result.output
    # warnings stream to stdout (mix_stderr); JSON is the trailing array
    json_part = result.output[result.output.index("[") :]
    data = json.loads(json_part)
    # other providers still returned their results
    assert len(data) == 6
    assert "failer search failed: boom" in (result.output + (result.stderr or ""))


def test_all_providers_fail_exits_nonzero(runner, monkeypatch):
    monkeypatch.setattr(
        "commands.search.register.build_providers",
        lambda config, tool_root=None: {"failer": _FailingPlugin()},
    )
    main = _main_with_reload()
    result = runner.invoke(main, ["search", "cats", "--format", "json"])
    assert result.exit_code == 1
    assert "failer search failed: boom" in (result.output + (result.stderr or ""))
