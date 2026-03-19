from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


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
    exit_code: int = 0
    error: Optional[str] = None

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)

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
            "exit_code": self.exit_code,
            "error": self.error,
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml(), encoding="utf-8")
