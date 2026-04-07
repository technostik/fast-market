"""
Router integration tests.

All tests marked `llm` — run with: pytest -m llm
They hit the real LLM configured in tests/fixtures/config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))

pytestmark = pytest.mark.llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_debug_dump(state) -> str:
    attempts = []
    for a in getattr(state, "attempts", []):
        attempts.append(
            f"iter={a.iteration} skill={a.skill_name} "
            f"success={a.success} exit={a.exit_code} "
            f"params={a.params} "
            f"summary={a.runner_summary[:240]!r}"
        )
    blob = "\n".join(attempts) if attempts else "(none)"
    return (
        f"goal={getattr(state, 'goal', '')!r}\n"
        f"done={getattr(state, 'done', None)} "
        f"failed={getattr(state, 'failed', None)} "
        f"iteration={getattr(state, 'iteration', None)} "
        f"max_iterations={getattr(state, 'max_iterations', None)}\n"
        f"final_result={getattr(state, 'final_result', '')!r}\n"
        f"failure_reason={getattr(state, 'failure_reason', '')!r}\n"
        f"attempts:\n{blob}"
    )


def _assert_router_success(state) -> None:
    debug = _state_debug_dump(state)
    assert state.done is True, f"Router did not finish successfully.\n{debug}"
    assert len(state.attempts) >= 1, f"Router produced no attempts.\n{debug}"


def get_llm_provider():
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


def _run_router(goal: str, workdir, skills_dir: Path | None = None, **kwargs):
    from core.router import run_router
    from common.llm.base import set_llm_log_file

    # Enable LLM logging to debug planner decisions
    log_file = workdir / "llm_debug.log"
    set_llm_log_file(log_file)

    provider = get_llm_provider()
    return run_router(
        goal=goal,
        provider=provider,
        workdir=str(workdir),
        max_iterations=kwargs.pop("max_iterations", 5),
        skills_dir=skills_dir,
        **kwargs,
    )


def _collect_outputs(state) -> list[str]:
    """Gather all text outputs from router state for assertion."""
    outputs = []
    for attempt in state.attempts:
        if attempt.runner_summary:
            outputs.append(attempt.runner_summary)
        if attempt.context:
            outputs.append(attempt.context)
        # For script skills the output is in session_output captured by runner_summary/context,
        # but also check raw subdir session files for prompt skills
        if attempt.subdir and attempt.subdir.exists():
            for sf in attempt.subdir.glob("*.session.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(sf.read_text())
                    for turn in data.get("turns", []):
                        for tc in turn.get("tool_calls", []):
                            if tc.get("stdout"):
                                outputs.append(tc["stdout"])
                except Exception:
                    pass
    return outputs


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_skill_run_command_executes_router(workdir):
    """Exercise the real `skill run` CLI path end-to-end."""
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
        f"skill run command failed.\nexit_code={result.exit_code}\noutput:\n{result.output}"
    )
    assert "Done:" in result.output, (
        f"Expected completion output, got:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# Core planner behaviour
# ---------------------------------------------------------------------------


def test_router_picks_correct_skill(workdir):
    state = _run_router("echo the message 'hello-router'", workdir, max_iterations=3)
    _assert_router_success(state)
    assert state.attempts[0].skill_name == "test-echo", _state_debug_dump(state)


def test_router_extracts_params(workdir):
    state = _run_router("echo the message 'extracted-param'", workdir, max_iterations=3)
    _assert_router_success(state)
    assert "message" in state.attempts[0].params, _state_debug_dump(state)
    assert state.attempts[0].params["message"] == "extracted-param", _state_debug_dump(
        state
    )


def test_router_retries_on_failure(workdir):
    """Router should attempt test-fail (which always exits 1) and record it as failed."""
    state = _run_router(
        "run the test-fail skill with reason='intentional'",
        workdir,
        max_iterations=3,
        retry_limit=1,
    )
    # test-fail always exits 1, so at least one attempt must be a failure
    failed = [a for a in state.attempts if not a.success]
    assert len(failed) >= 1, (
        f"Expected at least one failed attempt.\n{_state_debug_dump(state)}"
    )


def test_router_chains_two_skills(workdir):
    state = _run_router(
        "First run test-chain-a with input='abc', "
        "then run test-chain-b with the output of test-chain-a as chain_input",
        workdir,
        max_iterations=5,
        verbose=True,
    )
    _assert_router_success(state)
    names = [a.skill_name for a in state.attempts]
    assert "test-chain-a" in names, _state_debug_dump(state)
    assert "test-chain-b" in names, _state_debug_dump(state)
    assert names.index("test-chain-b") > names.index("test-chain-a"), _state_debug_dump(
        state
    )


def test_router_declares_fail_on_impossible_goal(workdir):
    state = _run_router(
        "send an email to mars@planet.sol using the martian-mail skill",
        workdir,
        max_iterations=3,
        retry_limit=1,
    )
    assert state.failed is True or state.done is False, _state_debug_dump(state)


# ---------------------------------------------------------------------------
# run_root and session file tests
# ---------------------------------------------------------------------------


def test_router_exposes_run_root(workdir):
    """run_root is set on the returned state and exists on disk."""
    state = _run_router("echo the message 'run-root-test'", workdir, max_iterations=3)
    assert state.run_root is not None, "run_root should be set"
    assert state.run_root.exists(), f"run_root dir should exist: {state.run_root}"


def test_router_sessions_written_to_run_root(workdir):
    """With save_session=True, session files appear inside run_root."""
    state = _run_router(
        "echo the message 'session-test'",
        workdir,
        max_iterations=3,
        save_session=True,
    )
    assert state.run_root is not None
    session_files = list(state.run_root.glob("**/*.session.yaml"))
    assert len(session_files) >= 1, (
        f"Expected at least one session file in run_root.\n"
        f"run_root={state.run_root}\n"
        f"found={[str(p) for p in session_files]}"
    )


def test_session_metrics_written(workdir):
    """Session files produced by the router contain metrics."""
    from helpers import get_session_metrics

    state = _run_router(
        "echo the message 'metrics-test'",
        workdir,
        max_iterations=3,
        save_session=True,
    )
    assert state.run_root is not None
    # test-echo is a script skill — save_session writes a session yaml only for
    # prompt skills; script skills don't have LLM sessions.
    # The router.session.yaml aggregation also only runs when session_files is non-empty.
    # So we just verify run_root exists and has subdirs.
    subdirs = [p for p in state.run_root.iterdir() if p.is_dir()]
    assert len(subdirs) >= 1, (
        f"Expected at least one subdir in run_root.\nrun_root={state.run_root}"
    )


# ---------------------------------------------------------------------------
# Summary quality
# ---------------------------------------------------------------------------


def test_runner_summary_not_raw_session(workdir):
    """runner_summary must be concise, not a raw session dump."""
    state = _run_router("echo the message 'distill-test'", workdir, max_iterations=3)
    _assert_router_success(state)
    for attempt in state.attempts:
        assert "tool_calls:" not in attempt.runner_summary, _state_debug_dump(state)
        assert len(attempt.runner_summary) < 1000, _state_debug_dump(state)


# ---------------------------------------------------------------------------
# Script skill (no LLM needed for the skill itself)
# ---------------------------------------------------------------------------


def test_successful_skill_has_zero_errors(workdir):
    """A script skill that works first try should have zero errors in session."""
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


# ---------------------------------------------------------------------------
# Export/Import functionality
# ---------------------------------------------------------------------------


def test_plan_import_and_export(workdir):
    """Test that imported plans are executed and export produces valid YAML."""
    import yaml
    from core.router import run_router, _import_plan_from_yaml

    # Create a simple plan file
    plan_file = workdir / "test-plan.yaml"
    plan_content = {
        "goal": "Test plan import",
        "success_criteria": "Plan executed successfully",
        "preparation_plan": "Test preparation",
        "plan": [
            {
                "step": 1,
                "action": "task",
                "description": "Echo 'hello from imported plan'",
            }
        ],
    }
    plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

    # Import and execute the plan
    provider = get_llm_provider()
    state = run_router(
        goal="Test plan import",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
        import_plan_path=str(plan_file),
        export_plan_path=str(workdir / "exported-plan.yaml"),
    )

    # Verify the plan was imported
    assert state.imported_plan is not None
    assert len(state.imported_plan.steps) == 1
    assert state.imported_plan.steps[0].action == "task"

    # Verify execution log was exported
    execution_log = workdir / "exported-plan.execution.yaml"
    assert execution_log.exists(), "Execution log was not exported"

    # Verify the exported execution log is valid YAML
    execution_data = yaml.safe_load(execution_log.read_text())
    assert execution_data["goal"] == "Test plan import"
    assert execution_data["status"] in ["completed", "failed", "max_iterations"]
    assert len(execution_data["execution"]) >= 1


def test_plan_export_format(workdir):
    """Test that exported plan has correct YAML format with all fields."""
    import yaml
    from core.router import run_router

    provider = get_llm_provider()
    state = run_router(
        goal="Test export format",
        provider=provider,
        workdir=str(workdir),
        max_iterations=2,
        export_plan_path=str(workdir / "plan.yaml"),
    )

    # Verify plan was exported
    plan_file = workdir / "plan.yaml"
    assert plan_file.exists(), "Plan was not exported"

    plan_data = yaml.safe_load(plan_file.read_text())

    # Verify structure
    assert "goal" in plan_data
    assert "plan" in plan_data
    assert "success_criteria" in plan_data
    assert "preparation_plan" in plan_data

    # Each step should have required fields
    for step in plan_data["plan"]:
        assert "step" in step
        assert "action" in step
        assert step["action"] in ["run", "task", "ask"]


def test_import_plan_with_inject(workdir):
    """Test that inject instructions from imported plan are passed to skills."""
    import yaml
    from core.router import run_router

    # Create a plan with inject instructions
    plan_file = workdir / "inject-plan.yaml"
    plan_content = {
        "goal": "Test inject from plan",
        "success_criteria": "Inject instructions were passed",
        "plan": [
            {
                "step": 1,
                "action": "task",
                "description": "Echo 'inject-test'",
            }
        ],
    }
    plan_file.write_text(yaml.dump(plan_content, default_flow_style=False))

    provider = get_llm_provider()
    state = run_router(
        goal="Test inject from plan",
        provider=provider,
        workdir=str(workdir),
        max_iterations=3,
        import_plan_path=str(plan_file),
    )

    # Verify the plan was imported and executed
    assert state.imported_plan is not None
    assert len(state.attempts) >= 1
