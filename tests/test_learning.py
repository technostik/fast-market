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

import os
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


def _run_router(goal: str, workdir: str, skills_dir: Path | None = None):
    """Run skill router and return state."""
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal=goal,
        provider=provider,
        workdir=workdir,
        max_iterations=10,
        skills_dir=skills_dir,
        save_session=True,
    )
    return state


def _get_stdout_outputs(state) -> list[str]:
    """Extract all tool call stdout values from router state attempts."""
    outputs = []
    for attempt in state.attempts:
        if attempt.runner_summary:
            outputs.append(attempt.runner_summary)
        if attempt.context:
            outputs.append(attempt.context)
        if attempt.subdir and attempt.subdir.exists():
            session_files = list(attempt.subdir.glob("*.session.yaml"))
            if session_files:
                try:
                    import yaml

                    session_data = yaml.safe_load(session_files[0].read_text())
                    for turn in session_data.get("turns", []):
                        for tool_call in turn.get("tool_calls", []):
                            if tool_call.get("arguments", {}).get("stdout"):
                                outputs.append(tool_call["arguments"]["stdout"])
                except Exception:
                    pass
    return outputs


def _reverse(s: str) -> str:
    """Expected output of 'guess doit again STRING'."""
    return s[::-1]


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


# — skill apply --auto-learn tests —————————————————————————


def test_skill_apply_creates_learn_md(workdir, skills_dir):
    """skill apply --auto-learn should create LEARN.md with proper content."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()
    session_file = workdir / "session.yaml"
    result = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=hello",
            "--auto-learn",
            "--save-session",
            str(session_file),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")
    print(f"Return code: {result.returncode}")

    assert result.returncode == 0, f"skill apply failed: {result.stderr}"

    assert learn_path.exists(), "LEARN.md was not created"

    content = learn_path.read_text()
    print(f"LEARN.md content:\n{content}")

    assert len(content.strip()) > 50, f"LEARN.md is too short: {content}"


def test_learn_md_improves_subsequent_runs(workdir, skills_dir):
    """LEARN.md from first run should help second run succeed."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()

    run1_session = workdir / "run1-session.yaml"
    result1 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=first",
            "--auto-learn",
            "--save-session",
            str(run1_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Run 1 return code: {result1.returncode}")
    print(f"Run 1 stderr: {result1.stderr}")

    print(f"LEARN.md exists: {learn_path.exists()}")
    if learn_path.exists():
        print(f"LEARN.md content:\n{learn_path.read_text()[:500]}")

    if not run1_session.exists():
        raise RuntimeError(f"Run 1 session file was not created at {run1_session}")

    assert learn_path.exists(), (
        f"Run 1 did not create LEARN.md. stderr: {result1.stderr}"
    )

    run2_session = workdir / "run2-session.yaml"
    result2 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=second",
            "--save-session",
            str(run2_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Run 2 return code: {result2.returncode}")
    print(f"Run 2 stderr: {result2.stderr}")

    if not run2_session.exists():
        raise RuntimeError(f"Run 2 session file was not created at {run2_session}")

    assert result2.returncode == 0, (
        f"Run 2 failed with LEARN.md present. stderr: {result2.stderr}"
    )


def test_learn_md_reduces_errors(workdir, skills_dir):
    """Verify that LEARN.md reduces errors between applies - the core learning test.

    This tests skill apply --auto-learn:
    - Apply 1: with --auto-learn - creates LEARN.md from its own session
    - Apply 2: with LEARN.md - should have fewer errors/steps
    """
    from common.core.paths import get_skills_dir
    from helpers import count_session_errors, count_total_steps, count_total_rounds

    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()

    apply1_session = workdir / "apply1-session.yaml"
    result1 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=baseline1",
            "--auto-learn",
            "--save-session",
            str(apply1_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Apply 1 return code: {result1.returncode}")
    print(f"Apply 1 stderr: {result1.stderr}")

    if not apply1_session.exists():
        raise RuntimeError(f"Apply 1 session file was not created at {apply1_session}")

    baseline_steps = count_total_steps(apply1_session)
    baseline_rounds = count_total_rounds(apply1_session)
    baseline_errors = count_session_errors(apply1_session)

    print(
        f"Baseline: {baseline_errors} errors, {baseline_steps} steps, {baseline_rounds} rounds"
    )

    print(f"LEARN.md exists: {learn_path.exists()}")
    if learn_path.exists():
        learn_content = learn_path.read_text()
        print(f"LEARN.md content:\n{learn_content[:500]}")
        assert "_No lessons" not in learn_content, (
            f"Auto-learn failed to extract real lessons. Content: {learn_content}"
        )

    assert learn_path.exists(), "LEARN.md was not created by --auto-learn"

    apply2_session = workdir / "apply2-session.yaml"
    result2 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=afterlearn",
            "--save-session",
            str(apply2_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Apply 2 return code: {result2.returncode}")
    print(f"Apply 2 stderr: {result2.stderr}")

    if not apply2_session.exists():
        raise RuntimeError(f"Apply 2 session file was not created at {apply2_session}")

    steps_with_learn = count_total_steps(apply2_session)
    rounds_with_learn = count_total_rounds(apply2_session)
    errors_with_learn = count_session_errors(apply2_session)

    print(f"\n=== Learning Test Results ===")
    print(
        f"Baseline: {baseline_errors} errors, {baseline_steps} steps, {baseline_rounds} rounds"
    )
    print(
        f"With LEARN.md: {errors_with_learn} errors, {steps_with_learn} steps, {rounds_with_learn} rounds"
    )

    assert result2.returncode == 0, (
        f"Apply 2 failed with LEARN.md present. stderr: {result2.stderr}"
    )

    learn_content = learn_path.read_text()
    if "_No lessons" in learn_content:
        assert steps_with_learn < baseline_steps, (
            f"Learning placeholder did NOT reduce steps: baseline={baseline_steps} with_learn={steps_with_learn}"
        )
    else:
        assert steps_with_learn <= baseline_steps, (
            f"Learning did NOT reduce or maintain steps: baseline={baseline_steps} with_learn={steps_with_learn}"
        )


def test_learn_md_reduces_steps(workdir, skills_dir):
    """Verify that LEARN.md reduces total steps - the core learning test.

    This tests skill apply --auto-learn:
    - Apply 1: with --auto-learn - creates LEARN.md from its own session
    - Apply 2: with LEARN.md - should have fewer steps and exploratory commands
    """
    from helpers import (
        count_total_steps,
        count_total_rounds,
        count_exploratory_commands,
    )

    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()

    apply1_session = workdir / "apply1-session.yaml"
    result1 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=baseline1",
            "--auto-learn",
            "--save-session",
            str(apply1_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    if not apply1_session.exists():
        raise RuntimeError(f"Apply 1 session file was not created at {apply1_session}")

    baseline_steps = count_total_steps(apply1_session)
    baseline_rounds = count_total_rounds(apply1_session)
    baseline_guesses = count_exploratory_commands(apply1_session)

    print(
        f"Baseline: {baseline_steps} steps, {baseline_rounds} rounds, {baseline_guesses} exploratory commands"
    )

    assert learn_path.exists(), "LEARN.md was not created by --auto-learn"

    apply2_session = workdir / "apply2-session.yaml"
    result2 = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=afterlearn",
            "--save-session",
            str(apply2_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Apply 2 return code: {result2.returncode}")

    if not apply2_session.exists():
        raise RuntimeError(f"Apply 2 session file was not created at {apply2_session}")

    steps_with_learn = count_total_steps(apply2_session)
    rounds_with_learn = count_total_rounds(apply2_session)
    guesses_with_learn = count_exploratory_commands(apply2_session)

    print(f"\n=== Learning Steps Test Results ===")
    print(
        f"Baseline (no LEARN.md): {baseline_steps} steps, {baseline_rounds} rounds, {baseline_guesses} exploratory commands"
    )
    print(
        f"With LEARN.md: {steps_with_learn} steps, {rounds_with_learn} rounds, {guesses_with_learn} exploratory commands"
    )

    assert baseline_steps >= 1, "Baseline session has 0 steps"
    assert result2.returncode == 0, (
        f"Apply 2 failed with LEARN.md present. stderr: {result2.stderr}"
    )

    learn_content = learn_path.read_text()
    if "_No lessons" in learn_content:
        assert steps_with_learn < baseline_steps, (
            f"Learning placeholder did NOT reduce steps: baseline={baseline_steps} with_learn={steps_with_learn}"
        )
    else:
        assert steps_with_learn <= baseline_steps, (
            f"Learning did NOT reduce or maintain steps: baseline={baseline_steps} with_learn={steps_with_learn}"
        )


def test_run1_produces_correct_output(workdir, skills_dir):
    """First run produces correct output."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    state = _run_router(
        goal="Use the test-guess skill with input='hello'",
        workdir=str(workdir),
        skills_dir=skills_dir,
    )

    assert len(state.attempts) > 0, f"Router did nothing: {state}"

    outputs = _get_stdout_outputs(state)
    assert any("olleh" in o for o in outputs), f"Expected 'olleh' in outputs: {outputs}"


def test_router_with_learn_md_produces_correct_output(workdir, skills_dir):
    """With manual LEARN.md, the router should produce correct output."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    learn_path.write_text("""# Lessons Learned for test-guess

## What Works
- `guess doit again <STRING>` — reverses the input string

## What to Avoid
- `guess doit <STRING>` — missing required 'again' keyword

## Useful Commands
- `guess --help` — shows available commands (doit)
- `guess doit --help` — shows subcommand syntax (again required)
""")

    state = _run_router(
        goal="Use the test-guess skill with input='test'",
        workdir=str(workdir),
        skills_dir=skills_dir,
    )

    assert len(state.attempts) > 0, f"Router did nothing: {state}"

    outputs = _get_stdout_outputs(state)
    assert any("tset" in o for o in outputs), f"Expected 'tset' in outputs: {outputs}"


# — Cleanup fixture ————————————————————————————————


@pytest.fixture(autouse=True)
def cleanup_learn_md(skills_dir):
    """Remove LEARN.md before each test to ensure isolation between tests."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()
    yield
