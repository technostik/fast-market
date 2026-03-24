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

    def test_setup_help(self, runner):
        """Test that setup --help works."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--list-engines" in result.output
        assert "--add-engine" in result.output
        assert "--show-config" in result.output
        assert "-l" in result.output
        assert "-a" in result.output
        assert "-c" in result.output

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
    """Test setup wizard functionality."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_setup_show_config_path(self, runner, tmp_config_dir):
        """Test --show-config-path option."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "--show-config-path"])
        assert result.exit_code == 0
        assert "image.yaml" in result.output

    def test_setup_show_config(self, runner, tmp_config_dir):
        """Test --show-config option with no config file."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "--show-config"])
        assert result.exit_code == 0
        data = result.output
        assert "default_engine" in data or "engines" in data

    def test_setup_list_engines_empty(self, runner, tmp_config_dir):
        """Test --list-engines with no config."""
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["setup", "--list-engines"])
        assert result.exit_code == 0
        assert "No engines" in result.output or "flux2" in result.output
