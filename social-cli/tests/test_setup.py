"""Tests for setup show and setup edit commands."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


def _main_with_reload():
    import cli.main as cli_mod
    importlib.reload(cli_mod)
    return cli_mod.main


class TestSetupShow:
    def test_show_no_backends(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """When no backends have config, show informative message."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        main = _main_with_reload()
        result = runner.invoke(main, ["setup", "show"])
        assert result.exit_code == 0
        assert "No backend configurations found" in result.output

    def test_show_single_backend_missing(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Show status for a backend with no config."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        main = _main_with_reload()
        result = runner.invoke(main, ["setup", "show", "--backend", "twitter"])
        assert result.exit_code == 0
        data = yaml.safe_load(result.output)
        assert data["status"] == "not_found"
        assert "twitter" in data["path"]


class TestSetupEdit:
    def test_edit_creates_default(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Edit should create default config from plugin template if missing."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        main = _main_with_reload()
        # EDITOR=cat just reads the file without changing it
        monkeypatch.setenv("EDITOR", "cat")
        result = runner.invoke(main, ["setup", "edit", "--backend", "twitter"])
        assert result.exit_code == 0

        cfg_path = xdg / "social" / "twitter" / "config.yaml"
        assert cfg_path.exists()
        data = yaml.safe_load(cfg_path.read_text())
        assert isinstance(data, dict)
        assert "twitter_bearer_token" in data

    def test_edit_all_backends(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Edit without --backend should produce merged nested YAML."""
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        # Create a minimal config for twitter first
        twitter_cfg = xdg / "social" / "twitter" / "config.yaml"
        twitter_cfg.parent.mkdir(parents=True)
        twitter_cfg.write_text("twitter_bearer_token: test123\n")

        main = _main_with_reload()
        # Use a script that just writes a sentinel value
        sentinel_script = tmp_path / "editor.sh"
        sentinel_script.write_text('#!/bin/bash\necho "# edited" >> "$1"\n')
        sentinel_script.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(sentinel_script))

        result = runner.invoke(main, ["setup", "edit"])
        assert result.exit_code == 0
        assert "Configurations updated" in result.output
