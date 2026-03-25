import shutil
import socket

import pytest

pytestmark = pytest.mark.llm  # skip with: pytest -m "not llm"


def _require_router_runtime() -> None:
    """Skip when required runtime deps for router integration tests are unavailable."""
    if shutil.which("skill") is None:
        pytest.skip("'skill' command is not on PATH for router subprocess execution")

    try:
        with socket.create_connection(("localhost", 11434), timeout=1):
            return
    except OSError:
        pytest.skip("ollama is not running on localhost:11434")


def get_llm_provider():
    """Load and validate the test LLM provider from fixture config."""
    from common.core.config import load_tool_config, requires_common_config
    from common.llm.base import LLMRequest
    from common.llm.registry import discover_providers, get_default_provider_name

    _require_router_runtime()
    requires_common_config("skill", ["llm"])
    config = load_tool_config("skill")
    providers = discover_providers(config)
    name = get_default_provider_name(config)
    provider = providers[name]

    # Preflight: skip if configured model does not exist or endpoint is incompatible.
    try:
        provider.complete(
            LLMRequest(
                prompt="Return exactly: OK",
                temperature=0,
                max_tokens=8,
            )
        )
    except Exception as exc:  # pragma: no cover - exercised by environment failures
        msg = str(exc).lower()
        if "404" in msg or "model" in msg or "not found" in msg:
            pytest.skip(f"ollama model unavailable for tests: {exc}")
        raise

    return provider


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
    # goal mentions test-fail explicitly so router tries it, then must adapt
    state = run_router(
        goal="run test-fail skill, then echo 'recovered' to confirm recovery",
        provider=provider,
        workdir=str(workdir),
        max_iterations=5,
        retry_limit=1,
    )
    # router should have at least one failed attempt
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
    # chain-b must come after chain-a
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
    """Router history must contain distilled summaries, not raw yaml."""
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
        # distilled result should be short prose, not yaml
        assert "tool_calls:" not in attempt.distilled_result
        assert len(attempt.distilled_result) < 1000
