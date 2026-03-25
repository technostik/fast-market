"""
Learning validation tests.

Requires ollama. Run with: pytest tests/test_learning.py -m llm -s
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.llm

TRICKY_INPUT = Path(__file__).parent / "fixtures" / "data" / "test-tricky-input.txt"
EXPECTED_UNIQUE_WORDS = 8


def _reset_learn(skills_dir: Path, skill_name: str) -> Path:
    learn_path = skills_dir / skill_name / "LEARN.md"
    if learn_path.exists():
        learn_path.unlink()
    return learn_path


def get_llm_provider():
    from common.core.config import requires_common_config, load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name

    requires_common_config("skill", ["llm"])
    config = load_tool_config("skill")
    providers = discover_providers(config)
    name = get_default_provider_name(config)
    return providers[name]


def test_auto_learn_creates_learn_md(workdir, skills_dir, isolate_xdg):
    """After task apply --auto-learn on test-echo, LEARN.md exists and is non-empty."""
    import subprocess

    learn_path = _reset_learn(skills_dir, "test-echo")

    result = subprocess.run(
        [
            "task",
            "apply",
            "run test-echo skill with message='learning-test'",
            "--auto-learn",
            "--learn-skill",
            "test-echo",
            "--workdir",
            str(workdir),
        ],
        timeout=120,
    )
    assert result.returncode == 0

    assert learn_path.exists(), "LEARN.md was not created"
    content = learn_path.read_text(encoding="utf-8")
    assert len(content.strip()) > 20, "LEARN.md is empty or trivial"
    learn_path.unlink()


def test_auto_learn_content_is_markdown(workdir, skills_dir):
    """LEARN.md produced by auto-learn is markdown with expected sections."""
    import subprocess

    learn_path = _reset_learn(skills_dir, "test-echo")

    result = subprocess.run(
        [
            "task",
            "apply",
            "run test-echo skill with message='markdown-test'",
            "--auto-learn",
            "--learn-skill",
            "test-echo",
            "--workdir",
            str(workdir),
        ],
        timeout=120,
    )
    assert result.returncode == 0

    assert learn_path.exists()
    content = learn_path.read_text(encoding="utf-8")
    assert any(line.startswith("#") for line in content.splitlines())
    learn_path.unlink()


JUDGE_PROMPT = """You are evaluating a LEARN.md file produced after an agent learned
how to count unique words in a text file.

The correct command pipeline is:
  tr '[:upper:]' '[:lower:]' < file.txt | tr -cs '[:alpha:]' '\\n' | sort -u | wc -l

## LEARN.md content to evaluate:
{learn_content}

## Question
Does this LEARN.md file contain enough information for an agent to:
1. Avoid using `wc -w` directly (which counts total words, not unique)
2. Use a pipeline involving `sort -u` and `wc -l` or equivalent

Answer with ONLY one of:
PASS - the file contains the correct lesson
FAIL - the file is missing the key lesson
PARTIAL - the file hints at the right approach but is not explicit enough

Then on a new line, one sentence explanation.
"""


def test_learn_md_contains_correct_lesson(workdir, skills_dir, tmp_path):
    import subprocess

    learn_path = _reset_learn(skills_dir, "test-tricky")
    shutil.copy(TRICKY_INPUT, workdir / "input.txt")

    result = subprocess.run(
        [
            "task",
            "apply",
            (
                "Count unique words in input.txt using shell commands only "
                "(do NOT call skill apply). "
                "Use command pipelines and verify exactness."
            ),
            "--auto-learn",
            "--learn-skill",
            "test-tricky",
            "--workdir",
            str(workdir),
            "--max-iterations",
            "15",
        ],
        timeout=300,
    )
    assert result.returncode == 0

    assert learn_path.exists(), "LEARN.md was not created after tricky task"

    learn_content = learn_path.read_text(encoding="utf-8")
    assert len(learn_content.strip()) > 50

    provider = get_llm_provider()
    from common.llm.base import LLMRequest

    request = LLMRequest(
        prompt=JUDGE_PROMPT.format(learn_content=learn_content),
        temperature=0.0,
        max_tokens=200,
    )
    response = provider.complete(request)
    verdict = (response.content or "").strip().split("\n")[0].strip()

    assert verdict in ("PASS", "PARTIAL"), (
        f"LLM judge rated LEARN.md as FAIL.\nContent:\n{learn_content}\n\nJudge: {response.content}"
    )

    learn_path.unlink()


def test_learning_reduces_failures(workdir, skills_dir, tmp_path):
    import subprocess

    from tests.helpers import count_session_errors

    shutil.copy(TRICKY_INPUT, workdir / "input.txt")

    session_1 = workdir / "session-1.yaml"
    session_2 = workdir / "session-2.yaml"

    learn_path = _reset_learn(skills_dir, "test-tricky")

    result_1 = subprocess.run(
        [
            "task",
            "apply",
            (
                "Count unique words in input.txt using shell commands only "
                "(do NOT call skill apply)."
            ),
            "--auto-learn",
            "--learn-skill",
            "test-tricky",
            "--workdir",
            str(workdir),
            "--save-session",
            str(session_1),
            "--max-iterations",
            "15",
        ],
        timeout=300,
    )
    assert result_1.returncode == 0
    assert learn_path.exists()

    result_2 = subprocess.run(
        [
            "task",
            "apply",
            (
                "Count unique words in input.txt using shell commands only "
                "(do NOT call skill apply)."
            ),
            "--auto-learn",
            "--learn-skill",
            "test-tricky",
            "--workdir",
            str(workdir),
            "--save-session",
            str(session_2),
            "--max-iterations",
            "15",
        ],
        timeout=300,
    )
    assert result_2.returncode == 0

    errors_1 = count_session_errors(session_1)
    errors_2 = count_session_errors(session_2)

    assert errors_2 <= errors_1, (
        f"Learning did not reduce errors: run1={errors_1} run2={errors_2}.\n"
        f"LEARN.md content:\n{learn_path.read_text(encoding='utf-8')}"
    )

    print(f"\nError counts: run1={errors_1} run2={errors_2}")
    if errors_2 == 0:
        print("✓ Perfect: zero errors on second run")

    learn_path.unlink()
