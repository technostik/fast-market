"""Integration tests for the social CLI commands."""

from __future__ import annotations

import json
import importlib

import pytest
from click.testing import CliRunner


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


class TestCLIHelp:
    def test_help(self, runner: CliRunner):
        main = _main_with_reload()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "post" in result.output
        assert "search" in result.output


class TestPostCommand:
    def test_post_no_message(self, runner: CliRunner):
        main = _main_with_reload()
        result = runner.invoke(main, ["post"])
        assert result.exit_code != 0
        assert "No MESSAGE" in result.output or "No message" in result.output

    def test_post_unknown_backend(self, runner: CliRunner, monkeypatch):
        main = _main_with_reload()
        # Ensure no real config is loaded
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent_social_config")
        result = runner.invoke(main, ["post", "hello", "--backend", "unknown"])
        assert result.exit_code != 0


class TestSearchCommand:
    def test_search_unknown_backend(self, runner: CliRunner, monkeypatch):
        main = _main_with_reload()
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent_social_config")
        result = runner.invoke(main, ["search", "test", "--backend", "unknown"])
        assert result.exit_code != 0
