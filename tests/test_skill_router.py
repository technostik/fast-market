import pytest
from click.testing import CliRunner
import sys
from pathlib import Path

pytestmark = pytest.mark.llm  # run with: pytest -m llm


def _state_debug_dump(state) -> str:
    attempts = []
    for attempt in getattr(state, "attempts", []):
        attempts.append(
            (
                f"iter={attempt.iteration} skill={attempt.skill_name} "
                f"success={attempt.success} exit={attempt.exit_code} "
                f"params={attempt.params} "
                f"distilled={attempt.distilled_result[:240]!r}"
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
    assert "Done:" in result.output, f"Expected completion output, got:\n{result.output}"


def test_router_picks_correct_skill(workdir):
    from common.skill.router import run_router

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
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'extracted-param'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    _assert_router_progress(state)
    assert "message" in state.attempts[0].params, _state_debug_dump(state)
    assert state.attempts[0].params["message"] == "extracted-param", _state_debug_dump(state)


def test_router_retries_on_failure(workdir):
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="run test-fail skill, then echo 'recovered' to confirm recovery",
        provider=provider,
        workdir=str(workdir),
        max_iterations=5,
        retry_limit=1,
    )
    failed = [a for a in state.attempts if not a.success]
    assert len(failed) >= 1, f"Expected at least one failed attempt.\n{_state_debug_dump(state)}"


def test_router_chains_two_skills(workdir):
    from common.skill.router import run_router

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
    assert names.index("test-chain-b") > names.index("test-chain-a"), _state_debug_dump(state)


def test_router_declares_fail_on_impossible_goal(workdir):
    from common.skill.router import run_router

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
    from common.skill.router import run_router

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


def test_distilled_result_not_raw_session(workdir):
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'distill-test'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    _assert_router_progress(state)
    for attempt in state.attempts:
        assert "tool_calls:" not in attempt.distilled_result, _state_debug_dump(state)
        assert len(attempt.distilled_result) < 1000, _state_debug_dump(state)


def test_session_metrics_written(workdir, skills_dir):
    """Session files produced by router contain metrics."""
    from common.core.paths import get_cache_dir
    from common.skill.router import run_router
    from tests.helpers import get_session_metrics

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


def test_successful_skill_has_zero_errors(workdir):
    """A skill that works first try should have zero errors in session."""
    import subprocess

    from tests.helpers import count_session_errors

    session_file = workdir / "session.yaml"
    subprocess.run(
        [
            "skill",
            "apply",
            "test-echo",
            "message=zero-errors",
            "--save-session",
            str(session_file),
        ],
        timeout=60,
        check=True,
    )

    assert count_session_errors(session_file) == 0
