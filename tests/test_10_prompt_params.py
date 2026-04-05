"""
Test parameter injection in execute_skill_prompt() for prompt-mode skills
that declare parameters but have no {placeholder} in their body.

Run with: pytest tests/test_10_prompt_params.py -m llm -s -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
_SKILL_CLI = str(REPO_ROOT / "skill-cli")
_TASK_CLI = str(REPO_ROOT / "task-cli")

sys.path = [p for p in sys.path if p != _TASK_CLI]
if _SKILL_CLI not in sys.path:
    sys.path.insert(0, _SKILL_CLI)
elif sys.path[0] != _SKILL_CLI:
    sys.path.remove(_SKILL_CLI)
    sys.path.insert(0, _SKILL_CLI)

pytestmark = pytest.mark.llm


def get_llm_provider():
    from common.core.config import load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name

    config = load_tool_config("skill")
    providers = discover_providers(config)
    name = get_default_provider_name(config)
    return providers[name]


@pytest.mark.llm
def test_prompt_params_injected_when_no_placeholder(workdir, skills_dir):
    """
    A prompt-mode skill with parameters but no {placeholder} in its body
    must still receive those params in the task body so the LLM sees them.

    The test skill 'test-params-no-placeholder' instructs the LLM to echo
    the expected_value parameter to stdout.
    """
    from core.skill import Skill
    from core.runner import execute_skill_prompt

    skill = Skill.from_path(skills_dir / "test-params-no-placeholder")
    assert skill is not None, "test-params-no-placeholder skill not found"

    result = execute_skill_prompt(
        skill=skill,
        workdir=workdir,
        params={"expected_value": "INJECTED_42"},
        max_iterations=3,
    )

    assert result.exit_code == 0, (
        f"execute_skill_prompt failed: exit_code={result.exit_code}\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )

    combined_stdout = result.stdout
    assert "INJECTED_42" in combined_stdout, (
        f"Expected 'INJECTED_42' in stdout but got:\n{combined_stdout}"
    )
