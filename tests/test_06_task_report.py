from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner


def get_cli():
    repo_root = Path(__file__).resolve().parents[1]
    task_cli_path = str(repo_root / "task-cli")
    if task_cli_path in sys.path:
        sys.path.remove(task_cli_path)
    sys.path.insert(0, task_cli_path)
    sys.modules.pop("commands", None)
    sys.modules.pop("commands.task", None)
    from commands.task.register import report_cmd

    return report_cmd


def test_task_report_text_and_json(tmp_path):
    session_file = Path(tmp_path) / "session.yaml"
    session_file.write_text(
        """
task_description: demo
metrics:
  total_tool_calls: 2
  error_count: 1
  guess_count: 1
  success_rate: 0.5
turns:
  - role: assistant
    tool_calls:
      - arguments:
          command: test-cmd
        exit_code: 1
        stderr: boom
""".strip()
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    text_result = runner.invoke(get_cli(), [str(session_file)])
    assert text_result.exit_code == 0
    assert "Metrics" in text_result.output
    assert "Failures" in text_result.output

    json_result = runner.invoke(get_cli(), [str(session_file), "--format", "json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert payload["metrics"]["error_count"] == 1
    assert len(payload["failures"]) == 1
