from __future__ import annotations

from datetime import datetime

from core.session import Session, ToolCallEvent, Turn


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
