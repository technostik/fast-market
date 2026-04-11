"""Tests for browser session export/import functionality."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from common.agent.session import Session, ToolCallEvent, Turn


@pytest.fixture
def sample_session():
    """Create a sample session with mixed success/failure tool calls."""
    session = Session(
        task_description="Go to example.com and extract the heading",
        workdir="/tmp/test-workdir",
        provider="openai",
        model="gpt-4",
        max_iterations=10,
        task_params={"url": "https://example.com"},
        start_time=datetime(2026, 4, 11, 10, 0, 0),
        end_time=datetime(2026, 4, 11, 10, 5, 0),
        end_reason="success: model signaled task completion",
        exit_code=0,
    )

    turn1 = Turn(
        role="assistant",
        content="I'll navigate to example.com and extract the heading.",
        timestamp=datetime(2026, 4, 11, 10, 1, 0),
    )
    turn1.tool_calls.append(
        ToolCallEvent(
            tool_call_id="tc-1",
            tool_name="browse",
            arguments={"action": "navigate", "args": ["https://example.com"]},
            explanation="Navigate to the target website",
            exit_code=0,
            stdout="Navigated to https://example.com\nPage title: Example Domain",
            stderr="",
            result={"timed_out": False},
        )
    )
    turn1.tool_calls.append(
        ToolCallEvent(
            tool_call_id="tc-2",
            tool_name="browse",
            arguments={"action": "snapshot", "args": []},
            explanation="Get page structure",
            exit_code=0,
            stdout="- heading: Example Domain\n- text: This domain is for use in...",
            stderr="",
            result={"timed_out": False},
        )
    )
    session.add_turn(turn1)

    turn2 = Turn(
        role="assistant",
        content="I'll try to click a non-existent button.",
        timestamp=datetime(2026, 4, 11, 10, 2, 0),
    )
    turn2.tool_calls.append(
        ToolCallEvent(
            tool_call_id="tc-3",
            tool_name="browse",
            arguments={"action": "click", "args": ["@nonexistent"]},
            explanation="Click the button",
            exit_code=1,
            stdout="",
            stderr="Error: Element @nonexistent not found",
            error="Element not found",
            result={"timed_out": False},
        )
    )
    session.add_turn(turn2)

    return session


class TestSessionExport:
    """Tests for Session.to_export_yaml()."""

    def test_export_full_format(self, sample_session):
        """Full export should include task_description, session_metadata, and commands."""
        yaml_text = sample_session.to_export_yaml(commands_only=False)
        data = yaml.safe_load(yaml_text)

        assert "task_description" in data
        assert "session_metadata" in data
        assert "commands" in data

        assert data["task_description"] == "Go to example.com and extract the heading"
        meta = data["session_metadata"]
        assert meta["workdir"] == "/tmp/test-workdir"
        assert meta["provider"] == "openai"
        assert meta["exit_code"] == 0
        assert "metrics" in meta

    def test_export_commands_only(self, sample_session):
        """Commands-only export should omit stdout and result fields."""
        yaml_text = sample_session.to_export_yaml(commands_only=True)
        data = yaml.safe_load(yaml_text)

        assert "commands" in data
        for cmd in data["commands"]:
            assert "action" in cmd
            assert "args" in cmd
            assert "stdout" not in cmd, "commands-only should not include stdout"
            assert "result" not in cmd, "commands-only should not include result"

    def test_export_includes_failed_commands(self, sample_session):
        """Export should include failed commands with error info."""
        yaml_text = sample_session.to_export_yaml(commands_only=False)
        data = yaml.safe_load(yaml_text)

        failed_cmds = [c for c in data["commands"] if c.get("exit_code", 0) != 0]
        assert len(failed_cmds) == 1
        assert failed_cmds[0]["action"] == "click"
        assert "not found" in failed_cmds[0]["stderr"]

    def test_export_metrics_in_metadata(self, sample_session):
        """Export should include session metrics in session_metadata."""
        yaml_text = sample_session.to_export_yaml(commands_only=False)
        data = yaml.safe_load(yaml_text)

        metrics = data["session_metadata"]["metrics"]
        assert metrics["total_tool_calls"] == 3
        assert metrics["error_count"] == 1
        assert metrics["success_rate"] < 1.0


class TestSessionImport:
    """Tests for Session.load_export() and import functionality."""

    def test_load_export_full_format(self, sample_session, tmp_path):
        """Should load an export file and return normalized dict."""
        export_file = tmp_path / "export.yaml"
        export_file.write_text(sample_session.to_export_yaml())

        data = Session.load_export(export_file)
        assert "task_description" in data
        assert "commands" in data
        assert "session_metadata" in data
        assert len(data["commands"]) == 3

    def test_load_export_legacy_session_format(self, tmp_path):
        """Should also load a legacy session file (with 'turns' instead of 'commands')."""
        session = Session(
            task_description="Legacy task",
            workdir="/tmp/legacy",
            provider="openai",
            model="gpt-4",
            max_iterations=5,
            turns=[
                Turn(
                    role="assistant",
                    content="Legacy turn",
                    tool_calls=[
                        ToolCallEvent(
                            tool_call_id="tc-1",
                            tool_name="browse",
                            arguments={"action": "navigate", "args": ["https://test.com"]},
                            explanation="Navigate",
                            exit_code=0,
                            stdout="OK",
                            stderr="",
                        )
                    ],
                )
            ],
        )

        legacy_file = tmp_path / "legacy-session.yaml"
        legacy_file.write_text(session.to_yaml())

        data = Session.load_export(legacy_file)
        assert "commands" in data
        assert len(data["commands"]) == 1
        assert data["commands"][0]["action"] == "navigate"

    def test_load_export_invalid_file(self, tmp_path):
        """Should raise ValueError for invalid YAML."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not: a: valid: yaml: [")

        with pytest.raises(Exception):
            Session.load_export(bad_file)


class TestSessionLoad:
    """Tests for Session.load()."""

    def test_load_roundtrip(self, sample_session, tmp_path):
        """Should save and load a session with all data intact."""
        session_file = tmp_path / "session.yaml"
        sample_session.save(session_file)

        loaded = Session.load(session_file)
        assert loaded.task_description == sample_session.task_description
        assert loaded.workdir == sample_session.workdir
        assert loaded.provider == sample_session.provider
        assert len(loaded.turns) == len(sample_session.turns)
        assert loaded.total_tool_calls == sample_session.total_tool_calls


class TestFormatForImport:
    """Tests for Session.format_for_import()."""

    def test_format_contains_task(self, sample_session):
        """Formatted output should include the task description."""
        text = sample_session.format_for_import("Current task: similar")
        assert "Go to example.com" in text
        assert "Current task: similar" in text

    def test_format_contains_command_sequence(self, sample_session):
        """Formatted output should list all commands."""
        text = sample_session.format_for_import("Current task")
        assert "browse navigate" in text
        assert "browse snapshot" in text
        assert "browse click" in text

    def test_format_shows_failed_commands(self, sample_session):
        """Formatted output should highlight failed commands."""
        text = sample_session.format_for_import("Current task")
        assert "FAILED" in text
        assert "exit code 1" in text

    def test_format_shows_successful_commands(self, sample_session):
        """Formatted output should show successful commands."""
        text = sample_session.format_for_import("Current task")
        assert "OK (exit code 0)" in text

    def test_format_includes_metrics_summary(self, sample_session):
        """Formatted output should include metrics summary."""
        text = sample_session.format_for_import("Current task")
        assert "3 tool calls" in text
        assert "1 errors" in text


class TestExportDataToSessionDict:
    """Tests for the _export_data_to_session_dict helper."""

    def test_conversion_preserves_commands(self):
        """Converted data should have turns with tool_calls from commands."""
        # Use importlib to explicitly load from browser-cli, avoiding ambiguous
        # 'commands.run.register' which could resolve to skill-cli instead.
        import importlib.util
        from pathlib import Path

        browser_cli = Path(__file__).parent.parent / "browser-cli"
        browser_register = browser_cli / "commands" / "run" / "register.py"

        # Temporarily put browser-cli before skill-cli in sys.path so that
        # `from commands.helpers import ...` inside register.py resolves correctly.
        browser_cli_str = str(browser_cli)
        old_path = list(sys.path)
        # Save and temporarily remove any 'commands.*' modules from sys.modules
        # to prevent skill-cli's commands package from interfering
        old_modules = {k: v for k, v in sys.modules.items() if k.startswith("commands")}
        modules_to_remove = [k for k in sys.modules if k.startswith("commands")]
        for mod in modules_to_remove:
            del sys.modules[mod]
        try:
            sys.path = [p for p in sys.path if p != browser_cli_str]
            sys.path.insert(0, browser_cli_str)

            spec = importlib.util.spec_from_file_location("browser_run_register", browser_register)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path = old_path
            # Restore the original sys.modules state
            sys.modules.update(old_modules)

        _export_data_to_session_dict = module._export_data_to_session_dict

        export_data = {
            "task_description": "Test task",
            "session_metadata": {
                "workdir": "/tmp/test",
                "provider": "openai",
                "model": "gpt-4",
                "max_iterations": 10,
                "task_params": {},
                "start_time": "2026-04-11T10:00:00",
                "end_time": "2026-04-11T10:05:00",
                "end_reason": "success",
                "exit_code": 0,
                "error": None,
            },
            "commands": [
                {
                    "action": "navigate",
                    "args": ["https://example.com"],
                    "explanation": "Navigate to site",
                    "exit_code": 0,
                    "stdout": "OK",
                    "stderr": "",
                    "error": None,
                    "result": {"timed_out": False},
                }
            ],
        }

        session_data = _export_data_to_session_dict(export_data)
        assert session_data["task_description"] == "Test task"
        assert len(session_data["turns"]) == 1
        assert len(session_data["turns"][0]["tool_calls"]) == 1

        tc = session_data["turns"][0]["tool_calls"][0]
        assert tc["arguments"]["action"] == "navigate"
        assert tc["exit_code"] == 0
        assert tc["stdout"] == "OK"
