from __future__ import annotations

import pytest
from datetime import datetime
from pathlib import Path

from core.task_prompt import TaskPromptConfig, DEFAULT_PROMPT_TEMPLATE
from core.session import Session, Turn, ToolCallEvent


class TestTaskPromptConfig:
    def test_default_template_has_placeholders(self):
        assert "{task_description}" in DEFAULT_PROMPT_TEMPLATE
        assert "{workdir}" in DEFAULT_PROMPT_TEMPLATE
        assert "{command_docs}" in DEFAULT_PROMPT_TEMPLATE

    def test_from_yaml_loads_valid_prompt(self, tmp_path):
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text("""
name: test-prompt
description: A test prompt
template: |
  Task: {task_description}
  Workdir: {workdir}
""")

        config = TaskPromptConfig.from_yaml(prompt_file)
        assert config is not None
        assert config.name == "test-prompt"
        assert config.description == "A test prompt"
        assert "Task: {task_description}" in config.template

    def test_from_yaml_returns_none_for_missing_file(self):
        config = TaskPromptConfig.from_yaml(Path("/nonexistent/prompt.yaml"))
        assert config is None

    def test_render_fills_placeholders(self):
        config = TaskPromptConfig(
            name="test",
            template="Task: {task_description}\nWorkdir: {workdir}",
        )
        result = config.render(
            task_description="Test task",
            workdir="/tmp",
            command_docs="# Commands",
        )
        assert "Task: Test task" in result
        assert "Workdir: /tmp" in result

    def test_validate_returns_empty_for_valid_config(self):
        config = TaskPromptConfig(
            name="test",
            template="Task: {task_description}",
        )
        assert config.validate() == []

    def test_validate_returns_errors_for_missing_fields(self):
        config = TaskPromptConfig(name="", template="")
        errors = config.validate()
        assert "name is required" in errors
        assert "template is required" in errors

    def test_save_and_load_roundtrip(self, tmp_path):
        config = TaskPromptConfig(
            name="roundtrip",
            description="Testing save/load",
            template="Task: {task_description}",
        )
        path = tmp_path / "roundtrip.yaml"
        config.save(path)

        loaded = TaskPromptConfig.from_yaml(path)
        assert loaded is not None
        assert loaded.name == "roundtrip"
        assert loaded.description == "Testing save/load"


class TestSession:
    def test_session_initialization(self):
        session = Session(
            task_description="Test task",
            workdir="/tmp",
            provider="anthropic",
            model="claude",
            max_iterations=10,
        )
        assert session.task_description == "Test task"
        assert session.workdir == "/tmp"
        assert session.provider == "anthropic"
        assert session.max_iterations == 10
        assert session.exit_code == 0
        assert session.end_time is None

    def test_add_turn(self):
        session = Session(
            task_description="Test",
            workdir="/tmp",
            provider="test",
            model="test",
            max_iterations=5,
        )
        turn = Turn(role="user", content="Hello")
        session.add_turn(turn)
        assert len(session.turns) == 1
        assert session.turns[0].role == "user"

    def test_turn_to_dict(self):
        turn = Turn(role="assistant", content="I'll help")
        turn.tool_calls.append(
            ToolCallEvent(
                tool_call_id="tc1",
                tool_name="execute_command",
                arguments={"command": "ls"},
            )
        )
        data = turn.to_dict()
        assert data["role"] == "assistant"
        assert data["content"] == "I'll help"
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool_name"] == "execute_command"

    def test_session_to_yaml(self):
        session = Session(
            task_description="Test task",
            workdir="/tmp",
            provider="anthropic",
            model="claude",
            max_iterations=10,
        )
        session.add_turn(Turn(role="user", content="Do something"))

        yaml_output = session.to_yaml()
        assert "task_description: Test task" in yaml_output
        assert "role: user" in yaml_output
        assert "provider: anthropic" in yaml_output

    def test_session_save(self, tmp_path):
        session = Session(
            task_description="Test",
            workdir="/tmp",
            provider="test",
            model="test",
            max_iterations=5,
        )
        session.end_time = datetime.utcnow()

        path = tmp_path / "session.yaml"
        session.save(path)
        assert path.exists()

        content = path.read_text()
        assert "task_description: Test" in content

    def test_tool_call_event(self):
        tc_event = ToolCallEvent(
            tool_call_id="abc123",
            tool_name="execute_command",
            arguments={"command": "ls -la"},
            explanation="Listing files",
            exit_code=0,
            stdout="file1.txt\nfile2.txt",
        )
        assert tc_event.exit_code == 0
        assert tc_event.stdout == "file1.txt\nfile2.txt"
        assert tc_event.explanation == "Listing files"

    def test_session_with_task_params(self):
        session = Session(
            task_description="Analyze data",
            workdir="/tmp",
            provider="test",
            model="test",
            max_iterations=10,
            task_params={"input": "data.csv", "format": "csv"},
        )
        assert session.task_params["input"] == "data.csv"
        assert session.task_params["format"] == "csv"
