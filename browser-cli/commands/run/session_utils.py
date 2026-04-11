"""Utility functions for browser session format conversion.

These pure functions handle conversion between export format (with 'commands' key)
and session format (with 'turns' key) without importing any CLI dependencies.
"""

from __future__ import annotations

from datetime import datetime


def export_data_to_session_dict(data: dict) -> dict:
    """Convert export-format dict (with 'commands' key) back to session-format
    dict (with 'turns' key) so it can be loaded via ``Session.from_dict()``.

    The export format flattens commands, while the session format organises
    them into turns.  For import purposes we create a single assistant turn
    containing all commands.
    """
    tool_calls = []
    for i, cmd in enumerate(data.get("commands", [])):
        tool_calls.append({
            "tool_call_id": f"import-{i}",
            "tool_name": "browse",
            "arguments": {
                "action": cmd.get("action", ""),
                "args": cmd.get("args", []),
                "explanation": cmd.get("explanation", ""),
            },
            "explanation": cmd.get("explanation", ""),
            "exit_code": cmd.get("exit_code"),
            "stdout": cmd.get("stdout", ""),
            "stderr": cmd.get("stderr", ""),
            "error": cmd.get("error"),
            "result": cmd.get("result"),
        })

    meta = data.get("session_metadata", {})
    return {
        "task_description": data.get("task_description", ""),
        "workdir": meta.get("workdir", ""),
        "provider": meta.get("provider", ""),
        "model": meta.get("model", ""),
        "max_iterations": meta.get("max_iterations", 20),
        "task_params": meta.get("task_params", {}),
        "turns": [
            {
                "role": "assistant",
                "content": "Imported session reference",
                "timestamp": meta.get("start_time", datetime.utcnow().isoformat()),
                "tool_calls": tool_calls,
            }
        ],
        "start_time": meta.get("start_time", datetime.utcnow().isoformat()),
        "end_time": meta.get("end_time"),
        "end_reason": meta.get("end_reason", ""),
        "exit_code": meta.get("exit_code", 0),
        "error": meta.get("error"),
    }
