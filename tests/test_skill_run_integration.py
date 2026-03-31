"""
Integration test: skill run full pipeline with session saving and auto-skill creation.

What this test proves:
  1. run_router() executes 2 script skills (test-chain-a, test-chain-b) and 1 raw task
  2. Each step produces an isolated subdir with a *.session.yaml
  3. router.session.yaml is aggregated and valid
  4. create_skill_from_session() produces a valid SKILL.md

Design decisions:
  - sys.path is patched at module level to put skill-cli first and exclude task-cli,
    preventing the `commands.setup` package collision (both CLIs have one).
  - Direct in-process calls only — no subprocess for router or skill creation.
  - Assertions ordered fail-fast: router outcome → session file → subdirs →
    per-subdir sessions → attempt types → skill creation.
  - The raw "task" step is asserted structurally (subdir + session.yaml,
    action="task" in state.attempts) — not by LLM-produced file content.

Run with:
  pytest tests/test_skill_run_integration.py -m llm -s -v
"""

from __future__ import annotations

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

# Remove task-cli if present, then ensure skill-cli is at front.
sys.path = [p for p in sys.path if p != _TASK_CLI]
if _SKILL_CLI not in sys.path:
    sys.path.insert(0, _SKILL_CLI)
elif sys.path[0] != _SKILL_CLI:
    sys.path.remove(_SKILL_CLI)
    sys.path.insert(0, _SKILL_CLI)

pytestmark = pytest.mark.llm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm_provider(isolate_xdg):
    """Resolve the default LLM provider from the fixture config."""
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


@pytest.fixture(autouse=True)
def cleanup_created_skills(skills_dir):
    """Remove any skill directories created during the test."""
    before = {d.name for d in skills_dir.iterdir() if d.is_dir()}
    yield
    for d in skills_dir.iterdir():
        if d.is_dir() and d.name not in before:
            shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, asserting it exists and is non-empty."""
    assert path.exists(), f"Expected file not found: {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data, f"File is empty or unparseable: {path}"
    return data


def _iter_subdirs(workdir: Path) -> list[Path]:
    """Return iteration subdirs sorted by name (supports optional prefix like 'a1b202_01_skill')."""
    return sorted(
        (d for d in workdir.iterdir() if d.is_dir() and _has_iteration_suffix(d.name)),
        key=lambda d: d.name,
    )


def _has_iteration_suffix(name: str) -> bool:
    """Check if name has a NN_* suffix (with optional prefix)."""
    parts = name.split("_")
    if len(parts) >= 2:
        return parts[-2][:2].isdigit()
    return False


def _find_router_session(workdir: Path) -> Path | None:
    """Find router.session.yaml (with any prefix)."""
    for f in workdir.iterdir():
        if f.is_file() and f.name.endswith("router.session.yaml"):
            return f
    return None


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_skill_run_full_pipeline(workdir, skills_dir, llm_provider):
    """
    Full pipeline: 2 chained script skills + 1 raw task step.

    Fail-fast assertion order:
      1. Router completes (state.done, not state.failed)
      2. router.session.yaml exists, exit_code=0, has >=2 turns
      3. >=3 iteration subdirs exist (one per skill + one for the task)
      4. Every subdir has a *.session.yaml
      5. state.attempts has test-chain-a, test-chain-b (action=run) and >=1 task
      6. Auto-created skill has a valid, substantive SKILL.md
    """
    from core.router import run_router
    from core.session_to_skill import create_skill_from_session

    GOAL = (
        "First run test-chain-a with input='pipeline-test', "
        "then run test-chain-b using the output as chain_input, "
        "then use a raw task to summarise both results in one sentence "
        "and print it to stdout."
    )

    # ------------------------------------------------------------------
    # 1. run_router — direct in-process call
    # ------------------------------------------------------------------
    state = run_router(
        goal=GOAL,
        provider=llm_provider,
        model=None,
        workdir=str(workdir),
        max_iterations=8,
        save_session=True,
        skip_evaluation=True,
    )

    assert not state.failed, (
        f"Router declared failure: {state.failure_reason}\n"
        f"Attempts: {[(a.skill_name, a.action, a.success) for a in state.attempts]}"
    )
    assert state.done, (
        f"Router did not complete within max_iterations.\n"
        f"Attempts: {[(a.skill_name, a.action, a.success) for a in state.attempts]}"
    )

    # ------------------------------------------------------------------
    # 2. router.session.yaml — existence, validity, exit_code, turns
    # ------------------------------------------------------------------
    session_path = _find_router_session(workdir)
    assert session_path is not None, "router.session.yaml not found in workdir"
    session_data = _load_yaml(session_path)

    assert session_data.get("exit_code") == 0, (
        f"router.session.yaml reports failure: "
        f"exit_code={session_data.get('exit_code')}, "
        f"end_reason={session_data.get('end_reason')!r}"
    )
    turns = session_data.get("turns", [])
    assert len(turns) >= 2, (
        f"Expected >=2 turns in aggregated session, got {len(turns)}"
    )

    # ------------------------------------------------------------------
    # 3. Iteration subdirs — at least 3 (chain-a, chain-b, task)
    # ------------------------------------------------------------------
    subdirs = _iter_subdirs(workdir)
    assert len(subdirs) >= 3, (
        f"Expected >=3 NN_* subdirs (one per skill + task), "
        f"found {len(subdirs)}: {[d.name for d in subdirs]}"
    )

    # ------------------------------------------------------------------
    # 4. Every subdir must have a *.session.yaml
    # ------------------------------------------------------------------
    for subdir in subdirs:
        session_files = list(subdir.glob("*.session.yaml"))
        assert session_files, (
            f"Subdir '{subdir.name}' has no *.session.yaml.\n"
            f"Contents: {[f.name for f in subdir.iterdir()]}"
        )

    # ------------------------------------------------------------------
    # 5. RouterState.attempts — skill names and task presence
    #    Query the live object directly; no re-parsing YAML.
    # ------------------------------------------------------------------
    skill_names = [a.skill_name for a in state.attempts if a.action == "run"]
    task_attempts = [a for a in state.attempts if a.action == "task"]

    assert "test-chain-a" in skill_names, (
        f"test-chain-a missing from skill attempts: {skill_names}"
    )
    assert "test-chain-b" in skill_names, (
        f"test-chain-b missing from skill attempts: {skill_names}"
    )
    assert len(task_attempts) >= 1, (
        f"Expected >=1 raw task attempt, got 0.\n"
        f"All attempts: {[(a.skill_name, a.action) for a in state.attempts]}"
    )

    # ------------------------------------------------------------------
    # 6. Auto-create skill from router session
    # ------------------------------------------------------------------
    CREATED_SKILL_NAME = "test-auto-pipeline"

    with (
        patch("core.session_to_skill.prompt_confirm", return_value=True),
        patch("core.session_to_skill.prompt_with_options", return_value="a"),
    ):
        create_skill_from_session(session_path, skill_name=CREATED_SKILL_NAME)

    new_skill_path = skills_dir / CREATED_SKILL_NAME
    assert new_skill_path.exists(), (
        f"Auto-created skill dir '{CREATED_SKILL_NAME}' not found in {skills_dir}"
    )

    skill_md = new_skill_path / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md missing in {new_skill_path}"

    content = skill_md.read_text(encoding="utf-8")
    assert len(content) > 200, (
        f"SKILL.md too short ({len(content)} chars) — likely a placeholder.\n"
        f"Content: {content}"
    )
    assert "---" in content, "SKILL.md has no YAML frontmatter (missing '---')"
