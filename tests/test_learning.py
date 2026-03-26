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


def _run_router(goal: str, workdir: str):
    """Run skill router and return state."""
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal=goal,
        provider=provider,
        workdir=workdir,
        max_iterations=10,
    )
    return state


def _get_stdout_outputs(state) -> list[str]:
    """Extract all tool call stdout values from router state attempts."""
    outputs = []
    for attempt in state.attempts:
        if attempt.distilled_result:
            outputs.append(attempt.distilled_result)
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

    # Run 1: Use skill run (router) to explore and potentially fail/learn
    result1 = subprocess.run(
        [
            "skill",
            "run",
            "Use the test-guess skill to process input='first'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "5",
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Run 1 return code: {result1.returncode}")
    print(f"Run 1 stderr: {result1.stderr}")

    # Check LEARN.md was created by checking skill directory
    # (The router should trigger auto-learn via skill apply)
    from common.core.paths import get_skills_dir

    test_guess_dir = get_skills_dir() / "test-guess"
    learn_path = test_guess_dir / "LEARN.md"

    print(f"LEARN.md exists: {learn_path.exists()}")
    if learn_path.exists():
        print(f"LEARN.md content:\n{learn_path.read_text()[:500]}")

    # For now, just verify the first run completed
    # Full error reduction test is done in test_learn_md_reduces_errors
    assert result1.returncode == 0 or learn_path.exists(), (
        f"Run 1 did not produce LEARN.md. stderr: {result1.stderr}"
    )


def test_learn_md_reduces_errors(workdir, skills_dir):
    """Verify that LEARN.md reduces errors between runs - the core learning test."""
    from common.core.paths import get_cache_dir, get_skills_dir

    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()

    # Run 1: Use skill run (router) to establish baseline - may have errors from exploration
    result1 = subprocess.run(
        [
            "skill",
            "run",
            "Use the test-guess skill to process input='baseline1'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "5",
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Run 1 return code: {result1.returncode}")
    print(f"Run 1 stderr: {result1.stderr}")

    # Get session files from cache
    cache = get_cache_dir() / "skill-router"
    session_files = sorted(cache.glob("session-*.yaml"))
    print(f"Session files in cache after run 1: {[f.name for f in session_files]}")

    # Debug: show raw session content
    for sf in session_files:
        print(f"\n=== Session: {sf.name} ===")
        print(sf.read_text()[:3000])

    errors_baseline = 0
    if session_files:
        from helpers import count_session_errors

        errors_baseline = count_session_errors(session_files[-1])
    print(f"Baseline run (no LEARN.md) errors: {errors_baseline}")

    # Run with auto-learn to create LEARN.md
    learn_session = workdir / "learn-session.yaml"
    result_learn = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=learn",
            "--auto-learn",
            "--save-session",
            str(learn_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Auto-learn return code: {result_learn.returncode}")
    print(f"Auto-learn stderr: {result_learn.stderr}")
    print(f"Auto-learn stdout: {result_learn.stdout}")

    # Check if session file was created
    print(f"Learn session file exists: {learn_session.exists()}")
    if learn_session.exists():
        print(f"Learn session content:\n{learn_session.read_text()[:1000]}")

    # Check LEARN.md was created
    fixture_learn = skills_dir / "test-guess" / "LEARN.md"
    print(f"LEARN.md exists in fixtures: {fixture_learn.exists()}")
    if fixture_learn.exists():
        print(f"LEARN.md content:\n{fixture_learn.read_text()[:500]}")

    # Also check actual skills dir
    actual_learn = get_skills_dir() / "test-guess" / "LEARN.md"
    print(f"LEARN.md exists in skills dir: {actual_learn.exists()}")

    # Run 2: With LEARN.md present - should have fewer errors
    result2 = subprocess.run(
        [
            "skill",
            "run",
            "Use the test-guess skill to process input='afterlearn'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "5",
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Run 2 return code: {result2.returncode}")
    print(f"Run 2 stderr: {result2.stderr}")

    # Get new session files
    session_files2 = sorted(cache.glob("session-*.yaml"))
    errors_with_learn = 0
    if len(session_files2) > len(session_files):
        from helpers import count_session_errors

        errors_with_learn = count_session_errors(session_files2[-1])

    print(f"\n=== Learning Test Results ===")
    print(f"Baseline (no LEARN.md): {errors_baseline} errors")
    print(f"With LEARN.md: {errors_with_learn} errors")

    # Check if LEARN.md exists in fixture directory
    fixture_learn = skills_dir / "test-guess" / "LEARN.md"
    if fixture_learn.exists():
        print(f"LEARN.md in fixtures:\n{fixture_learn.read_text()[:500]}")

    # Check in actual skills dir
    actual_learn = get_skills_dir() / "test-guess" / "LEARN.md"
    if actual_learn.exists():
        print(f"LEARN.md in actual skills dir:\n{actual_learn.read_text()[:500]}")

    # The key assertion: learning should strictly reduce errors OR steps
    # If both have 0 errors, check steps as fallback metric
    if errors_baseline == 0 and errors_with_learn == 0:
        from helpers import count_total_steps

        baseline_steps = count_total_steps(session_files[-1]) if session_files else 0
        steps_with_learn = (
            count_total_steps(session_files2[-1])
            if len(session_files2) > len(session_files)
            else 0
        )
        print(
            f"Fallback check - steps: baseline={baseline_steps}, with_learn={steps_with_learn}"
        )
        assert steps_with_learn >= 1, (
            f"Session with_learn has 0 steps - session may not have been created. "
            f"session_files: {[f.name for f in session_files2]}"
        )
        assert baseline_steps >= 1, (
            "Baseline session has 0 steps - session may not have been created"
        )
        assert steps_with_learn < baseline_steps, (
            f"Learning did NOT reduce steps: baseline={baseline_steps} with_learn={steps_with_learn}"
        )
    else:
        assert errors_with_learn < errors_baseline, (
            f"Learning did NOT reduce errors: baseline={errors_baseline} with_learn={errors_with_learn}"
        )


def test_learn_md_reduces_steps(workdir, skills_dir):
    """Verify that LEARN.md reduces total steps - the core learning test.

    Learning should:
    - Reduce total number of skill executions (steps)
    - Reduce exploratory commands (--help usage)
    - (Optionally) reduce errors
    """
    from common.core.paths import get_cache_dir
    from helpers import count_total_steps, count_exploratory_commands

    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    env = os.environ.copy()

    # Run 1: Without LEARN.md - establish baseline
    result1 = subprocess.run(
        [
            "skill",
            "run",
            "Use the test-guess skill to process input='baseline1'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "5",
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    cache = get_cache_dir() / "skill-router"
    session_files = sorted(cache.glob("session-*.yaml"))
    baseline_steps = count_total_steps(session_files[-1]) if session_files else 0
    baseline_guesses = (
        count_exploratory_commands(session_files[-1]) if session_files else 0
    )

    print(f"Baseline steps: {baseline_steps}, guesses: {baseline_guesses}")

    # Create LEARN.md via skill apply --auto-learn
    learn_session = workdir / "learn-session.yaml"
    result_learn = subprocess.run(
        [
            "skill",
            "apply",
            "test-guess",
            "input=learn",
            "--auto-learn",
            "--save-session",
            str(learn_session),
            "--workdir",
            str(workdir),
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    print(f"Auto-learn return code: {result_learn.returncode}")

    # Verify LEARN.md was created
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    print(f"LEARN.md exists: {learn_path.exists()}")

    # Run 2: With LEARN.md present - should use learned knowledge
    result2 = subprocess.run(
        [
            "skill",
            "run",
            "Use the test-guess skill to process input='afterlearn'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "5",
        ],
        env=env,
        timeout=180,
        capture_output=True,
        text=True,
    )

    session_files2 = sorted(cache.glob("session-*.yaml"))
    print(f"Session files after run 2: {[f.name for f in session_files2]}")

    # Get the latest session file (could be same as baseline if router reused iteration)
    latest_session = session_files2[-1] if session_files2 else None
    steps_with_learn = count_total_steps(latest_session) if latest_session else 0
    guesses_with_learn = (
        count_exploratory_commands(latest_session) if latest_session else 0
    )

    print(f"\n=== Learning Steps Test Results ===")
    print(
        f"Baseline (no LEARN.md): {baseline_steps} steps, {baseline_guesses} exploratory commands"
    )
    print(
        f"With LEARN.md: {steps_with_learn} steps, {guesses_with_learn} exploratory commands"
    )

    assert baseline_steps >= 1, (
        f"Baseline session has 0 steps - session may not have been created. "
        f"session_files: {[f.name for f in session_files]}"
    )
    assert steps_with_learn >= 1, (
        f"Session with_learn has 0 steps - session may not have been created. "
        f"session_files2: {[f.name for f in session_files2]}"
    )

    # The key assertion: learning should strictly reduce steps
    assert steps_with_learn < baseline_steps, (
        f"Learning did NOT reduce steps: baseline={baseline_steps} with_learn={steps_with_learn}"
    )

    # Secondary: exploratory commands should also reduce
    assert guesses_with_learn <= baseline_guesses, (
        f"Learning did NOT reduce exploratory commands: baseline={baseline_guesses} with_learn={guesses_with_learn}"
    )


def test_run1_produces_correct_output(workdir, skills_dir):
    """First run produces correct output."""
    learn_path = skills_dir / "test-guess" / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()

    state = _run_router(
        goal="Use the test-guess skill with input='hello'",
        workdir=str(workdir),
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
