"""
Learning validation tests using the 'guess' invented CLI command.

The 'guess' command requires reading --help TWICE to discover the correct
invocation: `guess doit again STRING`

This guarantees:
- Run 1: at least 1 failure (LLM tries wrong invocation first)
- Run 2: 0 failures if LEARN.md was written correctly

No LLM judge needed — verification is pure string comparison.

Requires: ollama running. Run with: pytest tests/test_learning.py -m llm -s
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.llm

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))


def get_llm_provider():
    from common.core.config import requires_common_config, load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name

    requires_common_config("skill", ["llm"])
    config = load_tool_config("skill")
    providers = discover_providers(config)
    name = get_default_provider_name(config)
    return providers[name]


def _run_task(
    task: str, workdir: Path, session_file: Path, auto_learn: bool = False
) -> int:
    """Run task apply and return exit code."""
    cmd = [
        "task",
        "apply",
        task,
        "--workdir",
        str(workdir),
        "--save-session",
        str(session_file),
        "--max-iterations",
        "10",
    ]
    if auto_learn:
        cmd += ["--auto-learn", "--learn-skill", "test-guess"]
    result = subprocess.run(cmd, timeout=180)
    return result.returncode


def _reverse(s: str) -> str:
    """Expected output of 'guess doit again STRING'."""
    return s[::-1]


def _get_stdout_outputs(session_file: Path) -> list[str]:
    """Extract all tool call stdout values from a session."""
    if not session_file.exists():
        return []
    data = yaml.safe_load(session_file.read_text())
    outputs = []
    for turn in data.get("turns", []):
        for tc in turn.get("tool_calls", []):
            stdout = tc.get("stdout", "").strip()
            if stdout:
                outputs.append(stdout)
    return outputs


# — Sanity check: guess command works correctly ————————————————


def test_guess_command_works():
    """Verify the guess binary itself works correctly before running LLM tests."""
    result = subprocess.run(
        ["guess", "doit", "again", "hello"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "olleh"


def test_guess_command_fails_without_again():
    """Verify wrong invocation fails — this is the trap for the LLM."""
    result = subprocess.run(["guess", "doit", "hello"], capture_output=True, text=True)
    assert result.returncode != 0


def test_guess_help_shows_doit():
    result = subprocess.run(["guess", "--help"], capture_output=True, text=True)
    assert "doit" in result.stdout


def test_guess_doit_help_shows_again():
    result = subprocess.run(["guess", "doit", "--help"], capture_output=True, text=True)
    assert "again" in result.stdout


# — Cleanup fixture ————————————————————————————————


@pytest.fixture(autouse=True)
def cleanup_learn_md(skills_dir):
    """Remove LEARN.md before each test to ensure isolation between tests."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()
    yield
