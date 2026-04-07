"""Shared context mechanism for multi-skill cooperation.

Provides a read/write string that skills can use to pass information between steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SharedContext:
    """A shared string that skills can read/write during a multi-skill run.

    Persisted to disk so it survives across skill executions within the same run.
    """

    content: str = ""
    save_path: Path | None = None

    def read(self) -> str:
        """Return the current context."""
        return self.content

    def write(self, content: str) -> str:
        """Replace the entire context. Returns the new content."""
        self.content = content
        self._save()
        return self.content

    def append(self, content: str) -> str:
        """Append to the context. Returns the new content."""
        if self.content:
            self.content = self.content + "\n\n" + content
        else:
            self.content = content
        self._save()
        return self.content

    def clear(self) -> str:
        """Clear the context. Returns empty string."""
        self.content = ""
        self._save()
        return self.content

    def _save(self) -> None:
        """Persist to disk if save_path is set."""
        if self.save_path is None:
            return
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(
            yaml.dump({"content": self.content}, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        logger.debug("shared_context_saved", path=str(self.save_path))

    @classmethod
    def load(cls, path: Path) -> SharedContext:
        """Load context from a YAML file."""
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return cls(content=data.get("content", ""), save_path=path)
        return cls(content="", save_path=path)


def build_shared_context_tool() -> dict[str, Any]:
    """Build the OpenAI-style tool definition for shared_context."""
    return {
        "type": "function",
        "function": {
            "name": "shared_context",
            "description": (
                "Read, write, append, or clear the shared context string. "
                "Use this to pass information between skills in a multi-skill run. "
                "Write key results, extracted data, or intermediate outputs so downstream skills can use them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "append", "clear"],
                        "description": (
                            "Action to perform: "
                            "'read' returns current content, "
                            "'write' replaces content, "
                            "'append' adds to content, "
                            "'clear' empties the context"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Content to write or append. Required for 'write' and 'append' actions."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }


def execute_shared_context(ctx: SharedContext, arguments: dict) -> str:
    """Execute a shared_context tool call. Returns the result string."""
    action = arguments.get("action", "")
    content = arguments.get("content", "")

    if action == "read":
        result = ctx.read()
        return result if result else "(empty)"

    if action == "write":
        if not content:
            return "Error: 'content' is required for 'write' action"
        result = ctx.write(content)
        return f"Context written ({len(result)} chars)"

    if action == "append":
        if not content:
            return "Error: 'content' is required for 'append' action"
        result = ctx.append(content)
        return f"Content appended ({len(result)} chars total)"

    if action == "clear":
        ctx.clear()
        return "Context cleared"

    return f"Error: unknown action '{action}'. Use: read, write, append, clear"
