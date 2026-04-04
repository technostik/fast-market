import pytest
from click.testing import CliRunner
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))

pytestmark = pytest.mark.llm  # run with: pytest -m llm


def _state_debug_dump(state) -> str:
    attempts = []
    for attempt in getattr(state, "attempts", []):
        attempts.append(
            (
                f"iter={attempt.iteration} skill={attempt.skill_name} "
                f"success={attempt.success} exit={attempt.exit_code} "
                f"params={attempt.params} "
                f"summary={attempt.runner_summary[:240]!r}"
            )
        )
    attempts_blob = "\n".join(attempts) if attempts else "(none)"
    return (
        f"goal={getattr(state, 'goal', '')!r}\n"
        f"done={getattr(state, 'done', None)} failed={getattr(state, 'failed', None)} "
        f"iteration={getattr(state, 'iteration', None)} max_iterations={getattr(state, 'max_iterations', None)}\n"
        f"final_result={getattr(state, 'final_result', '')!r}\n"
        f"failure_reason={getattr(state, 'failure_reason', '')!r}\n"
        f"attempts:\n{attempts_blob}"
    )


def _assert_router_progress(state, *, expected_done: bool = True) -> None:
    debug = _state_debug_dump(state)
    if expected_done:
        assert state.done is True, f"Router did not finish successfully.\n{debug}"
    assert len(state.attempts) >= 1, f"Router produced no attempts.\n{debug}"


def get_llm_provider():
    """Load the test LLM provider from fixture config."""
    from common.core.config import load_tool_config, requires_common_config
    from common.llm.registry import discover_providers, get_default_provider_name

    requires_common_config("skill", ["llm"])
    config = load_tool_config("skill")
    providers = discover_providers(config)
    name = get_default_provider_name(config)
    return providers[name]


def get_cli():
    repo_root = Path(__file__).resolve().parents[1]
    skill_cli_path = str(repo_root / "skill-cli")
    if skill_cli_path in sys.path:
        sys.path.remove(skill_cli_path)
    sys.path.insert(0, skill_cli_path)
    sys.modules.pop("commands", None)
    sys.modules.pop("commands.skill", None)
    from skill_entry import main

    return main


def test_skill_run_command_executes_router(workdir):
    """Exercise the real `skill run` CLI path with fixture LLM config."""
    runner = CliRunner()
    result = runner.invoke(
        get_cli(),
        [
            "run",
            "echo the message 'cli-run-check'",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "3",
            "--retry-limit",
            "1",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, (
        "skill run command failed.\n"
        f"exit_code={result.exit_code}\n"
        f"output:\n{result.output}"
    )
    assert "Done:" in result.output, (
        f"Expected completion output, got:\n{result.output}"
    )


def test_router_picks_correct_skill(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'hello-router'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    _assert_router_progress(state)
    assert state.attempts[0].skill_name == "test-echo", _state_debug_dump(state)


def test_router_extracts_params(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'extracted-param'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    _assert_router_progress(state)
    assert "message" in state.attempts[0].params, _state_debug_dump(state)
    assert state.attempts[0].params["message"] == "extracted-param", _state_debug_dump(
        state
    )


def test_router_retries_on_failure(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="run test-fail skill, then echo 'recovered' to confirm recovery",
        provider=provider,
        workdir=str(workdir),
        max_iterations=5,
        retry_limit=1,
    )
    failed = [a for a in state.attempts if not a.success]
    assert len(failed) >= 1, (
        f"Expected at least one failed attempt.\n{_state_debug_dump(state)}"
    )


def test_router_chains_two_skills(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal=(
            "First run test-chain-a with input='abc', "
            "then run test-chain-b with the output of test-chain-a as chain_input"
        ),
        provider=provider,
        workdir=str(workdir),
        max_iterations=5,
    )
    _assert_router_progress(state)
    names = [a.skill_name for a in state.attempts]
    assert "test-chain-a" in names, _state_debug_dump(state)
    assert "test-chain-b" in names, _state_debug_dump(state)
    assert names.index("test-chain-b") > names.index("test-chain-a"), _state_debug_dump(
        state
    )


def test_router_declares_fail_on_impossible_goal(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="send an email to mars@planet.sol using the martian-mail skill",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
        retry_limit=1,
    )
    assert state.failed is True or state.done is False, _state_debug_dump(state)


def test_router_sessions_written_to_cache(workdir, isolate_xdg):
    from common.core.paths import get_cache_dir
    from core.router import run_router

    provider = get_llm_provider()
    run_router(
        goal="echo the message 'cache-test'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    cache = get_cache_dir() / "skill-router"
    session_files = list(cache.glob("session-*.yaml"))
    assert len(session_files) >= 1, (
        "Expected at least one router session file in cache.\n"
        f"cache_dir={cache}\n"
        f"found_files={[str(p) for p in session_files]}"
    )


def test_runner_summary_not_raw_session(workdir):
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'distill-test'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    _assert_router_progress(state)
    for attempt in state.attempts:
        assert "tool_calls:" not in attempt.runner_summary, _state_debug_dump(state)
        assert len(attempt.runner_summary) < 1000, _state_debug_dump(state)


def test_session_metrics_written(workdir, skills_dir):
    """Session files produced by router contain metrics."""
    from common.core.paths import get_cache_dir
    from core.router import run_router
    from helpers import get_session_metrics

    provider = get_llm_provider()

    run_router(
        goal="echo the message 'metrics-test'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )

    cache = get_cache_dir() / "skill-router"
    session_files = sorted(cache.glob("session-*.yaml"))
    assert len(session_files) >= 1

    metrics = get_session_metrics(session_files[0])
    assert "error_count" in metrics
    assert "guess_count" in metrics
    assert "total_tool_calls" in metrics
    assert "success_rate" in metrics


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


def test_successful_skill_has_zero_errors(workdir):
    """A skill that works first try should have zero errors in session."""
    import subprocess

    from helpers import count_session_errors

    session_file = workdir / "session.yaml"
    subprocess.run(
        [
            "skill",
            "apply",
            "test-echo",
            "message=zero-errors",
            "--save-session",
            str(session_file),
            "--workdir",
            str(workdir),
        ],
        timeout=60,
        check=True,
    )

    assert count_session_errors(session_file) == 0
