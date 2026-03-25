import pytest
from click.testing import CliRunner

pytestmark = pytest.mark.llm  # run with: pytest -m llm


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
    assert result.exit_code == 0
    assert "Done:" in result.output


def test_router_picks_correct_skill(workdir):
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'hello-router'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    assert state.done is True
    assert len(state.attempts) >= 1
    assert state.attempts[0].skill_name == "test-echo"


def test_router_extracts_params(workdir):
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'extracted-param'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    assert state.done is True
    assert "message" in state.attempts[0].params
    assert state.attempts[0].params["message"] == "extracted-param"


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
    assert len(failed) >= 1


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
    assert state.done is True
    names = [a.skill_name for a in state.attempts]
    assert "test-chain-a" in names
    assert "test-chain-b" in names
    assert names.index("test-chain-b") > names.index("test-chain-a")


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
    assert state.failed is True or state.done is False


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
    assert len(session_files) >= 1


def test_distilled_result_not_raw_session(workdir):
    from common.skill.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="echo the message 'distill-test'",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
    )
    assert state.done is True
    for attempt in state.attempts:
        assert "tool_calls:" not in attempt.distilled_result
        assert len(attempt.distilled_result) < 1000
