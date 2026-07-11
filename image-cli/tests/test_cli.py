from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner


class TestCLICommands:
    """Test CLI commands without requiring actual model files."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_main_help(self, runner):
        """Test that main --help works."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["--help"])
        assert result.exit_code == 0
        assert "image" in result.output.lower()

    def test_generate_help(self, runner):
        """Test that generate --help works."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["generate", "--help"])
        assert result.exit_code == 0
        assert "PROMPT" in result.output
        assert "--engine" in result.output
        assert "--size" in result.output
        assert "--steps" in result.output
        assert "--title" in result.output
        assert "--position" in result.output
        assert "--overlay-effect" in result.output
        assert "--overlay-bg" in result.output
        assert "--overlay-style" in result.output

    def test_setup_help(self, runner):
        """Test that setup --help lists subcommands."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "--help"])
        assert result.exit_code == 0
        assert "wizard" in result.output
        assert "show" in result.output
        assert "edit" in result.output
        assert "reset" in result.output
        assert "engine" in result.output

    def test_serve_help(self, runner):
        """Test that serve --help works."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "-H" in result.output
        assert "-p" in result.output


class TestSetupWizard:
    """Test setup subcommands functionality."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_setup_show_config_path(self, runner, tmp_config_dir):
        """Test 'setup show --path' option."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "show", "--path"])
        assert result.exit_code == 0
        assert "config.yaml" in result.output
        assert "image" in result.output

    def test_setup_show_config(self, runner, tmp_config_dir):
        """Test 'setup show' with no config file (uses defaults)."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "show"])
        assert result.exit_code == 0
        data = result.output
        assert "default_engine" in data or "engines" in data

    def test_setup_show_engines(self, runner, tmp_config_dir):
        """Test 'setup show --engines' lists engines."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "show", "--engines"])
        assert result.exit_code == 0
        assert "flux2" in result.output

    def test_setup_engine_help(self, runner, tmp_config_dir):
        """Test 'setup engine' subcommand group."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "engine", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "remove" in result.output
        assert "set-default" in result.output
        assert "set-model-path" in result.output
