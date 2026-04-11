from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from common.core.yaml_utils import dump_yaml


@dataclass
class ToolCallEvent:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    explanation: str = ""
    result: Optional[dict[str, Any]] = None
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


@dataclass
class Turn:
    role: str
    content: str = ""
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        data = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "tool_calls": [],
        }
        for tc in self.tool_calls:
            tc_data = {
                "tool_call_id": tc.tool_call_id,
                "tool_name": tc.tool_name,
                "arguments": tc.arguments,
                "explanation": tc.explanation,
            }
            if tc.result is not None:
                tc_data["result"] = tc.result
            if tc.exit_code is not None:
                tc_data["exit_code"] = tc.exit_code
            if tc.stdout:
                tc_data["stdout"] = tc.stdout
            if tc.stderr:
                tc_data["stderr"] = tc.stderr
            if tc.error:
                tc_data["error"] = tc.error
            data["tool_calls"].append(tc_data)
        return data


@dataclass
class Session:
    task_description: str
    workdir: str
    provider: str
    model: str
    max_iterations: int
    task_params: dict[str, str] = field(default_factory=dict)
    turns: list[Turn] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    end_reason: str = ""
    exit_code: int = 0
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Create a Session from a dict (e.g., loaded from YAML)."""
        from datetime import datetime

        def parse_time(ts):
            if ts is None:
                return datetime.utcnow()
            if isinstance(ts, datetime):
                return ts
            if isinstance(ts, str):
                return datetime.fromisoformat(ts)
            return datetime.utcnow()

        turns = []
        for turn_data in data.get("turns", []):
            tool_calls = []
            for tc_data in turn_data.get("tool_calls", []):
                tc = ToolCallEvent(
                    tool_call_id=tc_data.get("tool_call_id", ""),
                    tool_name=tc_data.get("tool_name", ""),
                    arguments=tc_data.get("arguments", {}),
                    explanation=tc_data.get("explanation", ""),
                    result=tc_data.get("result"),
                    exit_code=tc_data.get("exit_code"),
                    stdout=tc_data.get("stdout", ""),
                    stderr=tc_data.get("stderr", ""),
                    error=tc_data.get("error"),
                )
                tool_calls.append(tc)
            turn = Turn(
                role=turn_data.get("role", "assistant"),
                content=turn_data.get("content", ""),
                tool_calls=tool_calls,
                timestamp=parse_time(turn_data.get("timestamp")),
            )
            turns.append(turn)

        return cls(
            task_description=data.get("task_description", ""),
            workdir=data.get("workdir", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            max_iterations=data.get("max_iterations", 20),
            task_params=data.get("task_params", {}),
            turns=turns,
            start_time=parse_time(data.get("start_time")),
            end_time=parse_time(data.get("end_time")),
            end_reason=data.get("end_reason", ""),
            exit_code=data.get("exit_code", 0),
            error=data.get("error"),
        )

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    @property
    def error_count(self) -> int:
        """Number of tool calls with non-zero exit code."""
        count = 0
        for turn in self.turns:
            for tc in turn.tool_calls:
                if tc.exit_code is not None and tc.exit_code != 0:
                    count += 1
        return count

    @property
    def guess_count(self) -> int:
        """
        Number of 'guess' tool calls.

        A guess is any tool call that immediately follows a failed tool call.
        """
        count = 0
        all_tool_calls = [tc for turn in self.turns for tc in turn.tool_calls]
        for i in range(1, len(all_tool_calls)):
            prev = all_tool_calls[i - 1]
            if prev.exit_code is not None and prev.exit_code != 0:
                count += 1
        return count

    @property
    def total_tool_calls(self) -> int:
        return sum(len(turn.tool_calls) for turn in self.turns)

    @property
    def success_rate(self) -> float:
        if self.total_tool_calls == 0:
            return 1.0
        return 1.0 - (self.error_count / self.total_tool_calls)

    def metrics_dict(self) -> dict[str, Any]:
        """Return session metrics as a serializable dict."""
        return {
            "total_tool_calls": self.total_tool_calls,
            "error_count": self.error_count,
            "guess_count": self.guess_count,
            "success_rate": round(self.success_rate, 3),
            "iterations_used": len([t for t in self.turns if t.role == "assistant"]),
        }

    def to_yaml(self) -> str:
        data = {
            "task_description": self.task_description,
            "workdir": self.workdir,
            "provider": self.provider,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "task_params": self.task_params,
            "turns": [turn.to_dict() for turn in self.turns],
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "end_reason": self.end_reason,
            "exit_code": self.exit_code,
            "error": self.error,
            "metrics": self.metrics_dict(),
        }
        return dump_yaml(data, sort_keys=False)

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Session":
        """Load a Session from a YAML file."""
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid session file: {path}")
        return cls.from_dict(data)

    # -- export helpers ------------------------------------------------------

    def to_export_yaml(self, commands_only: bool = False) -> str:
        """Serialize the session as an export YAML file.

        If *commands_only* is True, only the command sequence (action, args,
        explanation, exit_code, stderr, error) is included — stdout and
        detailed results are omitted to keep the export compact.
        """
        commands: list[dict[str, Any]] = []
        for turn in self.turns:
            for tc in turn.tool_calls:
                cmd = {
                    "action": tc.arguments.get("action", ""),
                    "args": tc.arguments.get("args", []),
                    "explanation": tc.explanation,
                }
                if tc.exit_code is not None:
                    cmd["exit_code"] = tc.exit_code
                if tc.stderr:
                    cmd["stderr"] = tc.stderr
                if tc.error:
                    cmd["error"] = tc.error
                if not commands_only:
                    if tc.stdout:
                        cmd["stdout"] = tc.stdout
                    if tc.result is not None:
                        cmd["result"] = tc.result
                commands.append(cmd)

        data: dict[str, Any] = {
            "task_description": self.task_description,
            "session_metadata": {
                "workdir": self.workdir,
                "provider": self.provider,
                "model": self.model,
                "max_iterations": self.max_iterations,
                "task_params": self.task_params,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "end_reason": self.end_reason,
                "exit_code": self.exit_code,
                "error": self.error,
                "metrics": self.metrics_dict(),
            },
            "commands": commands,
        }
        return dump_yaml(data, sort_keys=False)

    @staticmethod
    def load_export(path: Path) -> dict:
        """Load an exported session YAML file and return its raw dict.

        The file may be a full session export (from ``--export``) or a legacy
        full session file.  We normalise the structure so the caller always
        gets a consistent dict with ``task_description``, ``session_metadata``,
        and ``commands`` keys.
        """
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid session export file: {path}")

        # Detect format: export format has 'commands' at top level,
        # legacy session format has 'turns' at top level
        if "commands" in data:
            # Already in export format
            return data

        # Convert legacy session format to export format
        session = Session.from_dict(data)
        return yaml.safe_load(session.to_export_yaml())

    def format_for_import(self, current_task: str) -> str:
        """Format this session as a text block suitable for injecting into
        the system prompt when the agent is run with ``--import``.

        The output summarises the past session so the LLM can learn from it.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("PREVIOUS SESSION REFERENCE")
        lines.append(f"Task: {self.task_description}")
        lines.append(f"Match current task: {current_task}")
        lines.append("=" * 60)
        lines.append("")

        m = self.metrics_dict()
        lines.append(f"Summary: {m['total_tool_calls']} tool calls, "
                      f"{m['error_count']} errors, "
                      f"success rate {m['success_rate']:.0%}")
        if self.error:
            lines.append(f"Session error: {self.error}")
        lines.append("")

        # Group commands with their outcomes for LLM consumption
        lines.append("Command sequence:")
        for turn in self.turns:
            for tc in turn.tool_calls:
                action = tc.arguments.get("action", "")
                args = tc.arguments.get("args", [])
                args_str = " ".join(str(a) for a in args) if isinstance(args, list) else str(args)
                cmd_line = f"  browse {action} {args_str}"
                if tc.explanation:
                    cmd_line += f"  # {tc.explanation}"
                lines.append(cmd_line)

                if tc.exit_code is not None and tc.exit_code != 0:
                    lines.append(f"    -> FAILED (exit code {tc.exit_code})")
                    if tc.stderr:
                        stderr_preview = tc.stderr[:200]
                        lines.append(f"       stderr: {stderr_preview}")
                    if tc.error:
                        lines.append(f"       error: {tc.error}")
                elif tc.exit_code is not None:
                    lines.append(f"    -> OK (exit code 0)")
                lines.append("")

        lines.append("=" * 60)
        lines.append("END OF PREVIOUS SESSION")
        lines.append("=" * 60)

        return "\n".join(lines)
