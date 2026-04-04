from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from core.session import Session, ToolCallEvent, Turn

pytestmark = pytest.mark.llm


def test_skill_apply_session_has_metrics(workdir):
    """skill apply should create session with proper metrics."""
    session_file = workdir / "session.yaml"
    result = subprocess.run(
        [
            "skill",
            "apply",
            "test-echo",
            "message=hello",
            "--save-session",
            str(session_file),
            "--workdir",
            str(workdir),
        ],
        timeout=60,
        capture_output=True,
        text=True,
    )

    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")
    print(f"Return code: {result.returncode}")

    assert result.returncode == 0, f"skill apply failed: {result.stderr}"
    assert session_file.exists(), "Session file was not created"

    data = yaml.safe_load(session_file.read_text(encoding="utf-8"))
    assert "metrics" in data, "Session should have metrics"

    metrics = data["metrics"]
    assert "total_tool_calls" in metrics
    assert "error_count" in metrics
    assert "guess_count" in metrics
    assert "success_rate" in metrics

    assert metrics["total_tool_calls"] >= 1, "Should have at least 1 tool call"


def test_skill_apply_session_with_error_has_error_count(workdir):
    """skill apply with failing command should have error_count >= 1."""
    session_file = workdir / "session.yaml"
    result = subprocess.run(
        [
            "skill",
            "apply",
            "test-fail",
            "--save-session",
            str(session_file),
            "--workdir",
            str(workdir),
        ],
        timeout=60,
        capture_output=True,
        text=True,
    )

    print(f"Return code: {result.returncode}")

    assert session_file.exists(), "Session file was not created"

    data = yaml.safe_load(session_file.read_text(encoding="utf-8"))
    metrics = data["metrics"]

    assert metrics["error_count"] >= 1, "Should have at least 1 error"
    assert metrics["success_rate"] < 1.0, "Success rate should be less than 1.0"


def test_session_metrics_properties():
    session = Session(
        task_description="test",
        workdir=".",
        provider="ollama",
        model="qwen",
        max_iterations=5,
    )

    turn = Turn(role="assistant", content="step")
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="1",
            tool_name="execute_command",
            arguments={"command": "echo ok"},
            exit_code=0,
        )
    )
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="2",
            tool_name="execute_command",
            arguments={"command": "false"},
            exit_code=1,
        )
    )
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="3",
            tool_name="execute_command",
            arguments={"command": "echo retry"},
            exit_code=0,
        )
    )

    session.add_turn(turn)
    session.end_time = datetime.utcnow()

    assert session.total_tool_calls == 3
    assert session.error_count == 1
    assert session.guess_count == 1
    assert round(session.success_rate, 3) == round(2 / 3, 3)

    data = session.to_yaml()
    assert "metrics:" in data
    assert "error_count: 1" in data


def test_session_minimum_one_step():
    """Session with at least one tool call should have total_tool_calls >= 1."""
    session = Session(
        task_description="test",
        workdir=".",
        provider="ollama",
        model="qwen",
        max_iterations=5,
    )

    turn = Turn(role="assistant", content="step")
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="1",
            tool_name="execute_command",
            arguments={"command": "echo ok"},
            exit_code=0,
        )
    )

    session.add_turn(turn)
    session.end_time = datetime.utcnow()

    assert session.total_tool_calls >= 1, "Minimum tool calls should be 1"


def test_session_with_errors():
    """Session with failed commands should correctly count errors."""
    session = Session(
        task_description="test",
        workdir=".",
        provider="ollama",
        model="qwen",
        max_iterations=5,
    )

    turn = Turn(role="assistant", content="step")
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="1",
            tool_name="execute_command",
            arguments={"command": "wrong-command"},
            exit_code=1,
        )
    )

    session.add_turn(turn)
    session.end_time = datetime.utcnow()

    assert session.error_count == 1
    assert session.success_rate == 0.0


def test_session_guess_detection():
    """Session should detect guesses - tool calls after failed commands."""
    session = Session(
        task_description="test",
        workdir=".",
        provider="ollama",
        model="qwen",
        max_iterations=5,
    )

    turn = Turn(role="assistant", content="first attempt")
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="1",
            tool_name="execute_command",
            arguments={"command": "guess doit hello"},
            exit_code=1,
        )
    )
    turn.tool_calls.append(
        ToolCallEvent(
            tool_call_id="2",
            tool_name="execute_command",
            arguments={"command": "guess doit again hello"},
            exit_code=0,
        )
    )

    session.add_turn(turn)
    session.end_time = datetime.utcnow()

    assert session.guess_count == 1, (
        "Should detect 1 guess (command after failed attempt)"
    )
