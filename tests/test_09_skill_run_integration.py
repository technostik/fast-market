"""
Integration test: skill run full pipeline with session saving and auto-skill creation.

What this test proves:
  1. run_router() executes skills to achieve the pipeline goal
  2. Each step produces an isolated subdir with a *.session.yaml
  3. router.session.yaml is aggregated and valid
  4. create_skill_from_session() produces a valid SKILL.md

Design decisions:
  - sys.path is patched at module level to put skill-cli first and exclude task-cli,
    preventing the `commands.setup` package collision (both CLIs have one).
  - Direct in-process calls only — no subprocess for router or skill creation.
  - Fixtures run once per module; each test asserts one thing.
  - If router fixture fails, downstream tests are skipped (ERROR), not run blindly.

Run with:
  pytest tests/test_skill_run_integration.py -m llm -s -v
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# sys.path isolation — MUST happen before any skill-cli import.
#
# conftest.py inserts both skill-cli and task-cli into sys.path (session-scoped).
# Both expose a `commands` package, and Python resolves to whichever appears
# first. router.py does `from commands.setup import init_skill_agent_config`
# which only exists in skill-cli; if task-cli wins, the import fails.
#
# Solution: at module load time, promote skill-cli to position 0 and remove
# task-cli entirely from sys.path for the duration of this module's imports.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
_SKILL_CLI = str(_REPO_ROOT / "skill-cli")
_TASK_CLI = str(_REPO_ROOT / "task-cli")

sys.path = [p for p in sys.path if p != _TASK_CLI]
if _SKILL_CLI not in sys.path:
    sys.path.insert(0, _SKILL_CLI)
elif sys.path[0] != _SKILL_CLI:
    sys.path.remove(_SKILL_CLI)
    sys.path.insert(0, _SKILL_CLI)

pytestmark = pytest.mark.llm

GOAL = (
    "First run test-chain-a with input='pipeline-test', "
    "then run test-chain-b using the output as chain_input, "
    "then use a raw task to summarise both results in one sentence "
    "and print it to stdout."
)
CREATED_SKILL_NAME = "test-auto-pipeline"

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workdir_module(tmp_path_factory):
    """Stable workdir shared across all tests in this module."""
    return tmp_path_factory.mktemp("skill_run_integration")


@pytest.fixture(scope="module")
def llm_provider_module(isolate_xdg):
    """Module-scoped LLM provider."""
    from common.core.config import load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name

    config = load_tool_config("skill")
    providers = discover_providers(config)
    provider_name = get_default_provider_name(config)
    provider = providers.get(provider_name)
    assert provider is not None, (
        f"LLM provider '{provider_name}' not available. "
        "Check tests/fixtures/config/fast-market/common/llm/config.yaml."
    )
    return provider


@pytest.fixture(scope="module")
def router_outcome(workdir_module, llm_provider_module):
    """Run the router once. Returns (state, run_root)."""
    from core.router import run_router

    before = {d.name for d in workdir_module.iterdir() if d.is_dir()}

    state = run_router(
        goal=GOAL,
        provider=llm_provider_module,
        model=None,
        workdir=str(workdir_module),
        max_iterations=8,
        save_session=True,
        skip_evaluation=True,
    )

    after = {d.name for d in workdir_module.iterdir() if d.is_dir()}
    new_dirs = after - before
    assert len(new_dirs) == 1, (
        f"Expected exactly one run_root subdir created, found {len(new_dirs)}: {new_dirs}"
    )
    run_root = workdir_module / new_dirs.pop()

    return state, run_root


@pytest.fixture(scope="module")
def session_data(router_outcome):
    """Load router.session.yaml from run_root."""
    _, run_root = router_outcome
    session_path = run_root / "router.session.yaml"
    assert session_path.exists(), f"router.session.yaml not found in {run_root}"
    data = yaml.safe_load(session_path.read_text())
    assert data, f"router.session.yaml is empty or unparseable"
    return data


@pytest.fixture(scope="module")
def created_skill_path(router_outcome, isolate_xdg):
    """Auto-create skill from session. Returns path to the created skill dir."""
    from common.core.paths import get_skills_dir
    from core.session_to_skill import create_skill_from_session

    _, run_root = router_outcome
    session_path = run_root / "router.session.yaml"
    skills_dir = get_skills_dir()

    with (
        patch("core.session_to_skill.prompt_confirm", return_value=True),
        patch("core.session_to_skill.prompt_with_options", return_value="a"),
    ):
        create_skill_from_session(session_path, skill_name=CREATED_SKILL_NAME)

    new_skill_path = skills_dir / CREATED_SKILL_NAME
    yield new_skill_path

    if new_skill_path.exists():
        shutil.rmtree(new_skill_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_iteration_suffix(name: str) -> bool:
    """Check if name has a NN_* prefix."""
    return bool(re.match(r"\d{2}_", name))


def _find_router_session(run_root: Path) -> Path | None:
    """Find router.session.yaml by exact name."""
    p = run_root / "router.session.yaml"
    return p if p.exists() else None


def _iter_subdirs(workdir: Path) -> list[Path]:
    """Return iteration subdirs sorted by name."""
    return sorted(
        (d for d in workdir.iterdir() if d.is_dir() and _has_iteration_suffix(d.name)),
        key=lambda d: d.name,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_router_completes(router_outcome):
    """Assert router completed without failure."""
    state, _ = router_outcome
    assert not state.failed, (
        f"Router declared failure: {state.failure_reason}\n"
        f"Attempts: {[(a.skill_name, a.action, a.success) for a in state.attempts]}"
    )
    assert state.done, (
        f"Router did not complete within max_iterations.\n"
        f"Attempts: {[(a.skill_name, a.action, a.success) for a in state.attempts]}"
    )


def test_session_file_exists_and_valid(session_data):
    """Assert router.session.yaml exists, has exit_code=0 and end_reason."""
    assert session_data.get("exit_code") == 0, (
        f"router.session.yaml reports failure: "
        f"exit_code={session_data.get('exit_code')}, "
        f"end_reason={session_data.get('end_reason')!r}"
    )
    assert session_data.get("end_reason"), "router.session.yaml missing end_reason"


def test_session_has_tool_calls(session_data):
    """Assert at least one turn has tool_calls with exit_code=0."""
    turns = session_data.get("turns", [])
    assert len(turns) >= 1, f"Expected >=1 turn in session, got {len(turns)}"

    found_valid_tool_call = False
    for turn in turns:
        for tc in turn.get("tool_calls", []):
            exit_code = tc.get("exit_code")
            if exit_code == 0:
                found_valid_tool_call = True
                break
        if found_valid_tool_call:
            break

    assert found_valid_tool_call, "No tool_calls with exit_code=0 found in session"


def test_iteration_subdirs_exist(router_outcome):
    """Assert >=3 NN_* subdirs exist inside run_root."""
    _, run_root = router_outcome
    subdirs = _iter_subdirs(run_root)
    assert len(subdirs) >= 3, (
        f"Expected >=3 NN_* subdirs (one per skill + task), "
        f"found {len(subdirs)}: {[d.name for d in subdirs]}"
    )


def test_every_subdir_has_session(router_outcome):
    """Assert every NN_* subdir has a *.session.yaml."""
    _, run_root = router_outcome
    subdirs = _iter_subdirs(run_root)
    assert subdirs, f"No iteration subdirs found in {run_root}"
    for subdir in subdirs:
        session_files = list(subdir.glob("*.session.yaml"))
        assert session_files, (
            f"Subdir '{subdir.name}' has no *.session.yaml.\n"
            f"Contents: {[f.name for f in subdir.iterdir()]}"
        )


def test_chain_skills_ran_in_order(router_outcome):
    """Assert skill_names from run attempts: chain-a before chain-b."""
    state, _ = router_outcome
    skill_run_attempts = [a for a in state.attempts if a.action == "run"]
    skill_names = [a.skill_name for a in skill_run_attempts]

    assert "test-chain-a" in skill_names, (
        f"test-chain-a missing from skill attempts: {skill_names}"
    )
    assert "test-chain-b" in skill_names, (
        f"test-chain-b missing from skill attempts: {skill_names}"
    )

    idx_a = skill_names.index("test-chain-a")
    idx_b = skill_names.index("test-chain-b")
    assert idx_a < idx_b, (
        f"test-chain-a must run before test-chain-b (got {idx_a} vs {idx_b})"
    )


def test_task_step_ran(router_outcome):
    """Assert at least one attempt with action='task' or action='run' with test-echo."""
    state, _ = router_outcome
    all_attempts = state.attempts

    assert len(all_attempts) >= 1, f"Expected >=1 attempt, got 0."


def test_chain_outputs_in_session(session_data):
    """Assert the session has tool calls with non-empty stdout from the skills."""
    turns = session_data.get("turns", [])
    assert turns, "Expected turns in aggregated session"

    found_tool_call = False
    for turn in turns:
        for tc in turn.get("tool_calls", []):
            stdout = tc.get("stdout", "") or ""
            if stdout.strip():
                found_tool_call = True
                break
        if found_tool_call:
            break

    assert found_tool_call, "No non-empty stdout found in any tool_calls"


def test_auto_skill_created(created_skill_path):
    """Assert skill dir exists and SKILL.md exists with len > 200."""
    assert created_skill_path.exists(), (
        f"Auto-created skill dir not found in {created_skill_path}"
    )

    skill_md = created_skill_path / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md missing in {created_skill_path}"

    content = skill_md.read_text(encoding="utf-8")
    assert len(content) > 200, (
        f"SKILL.md too short ({len(content)} chars) — likely a placeholder.\n"
        f"Content: {content}"
    )


def test_auto_skill_frontmatter_valid(created_skill_path):
    """Assert parse frontmatter YAML and name == CREATED_SKILL_NAME."""
    skill_md = created_skill_path / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")

    assert "---" in content, "SKILL.md has no YAML frontmatter (missing '---')"

    parts = content.split("---", 2)
    assert len(parts) >= 3, "SKILL.md frontmatter malformed"

    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter is not None, "Frontmatter is empty or unparseable"
    assert frontmatter.get("name") == CREATED_SKILL_NAME, (
        f"Expected name={CREATED_SKILL_NAME}, got {frontmatter.get('name')}"
    )
