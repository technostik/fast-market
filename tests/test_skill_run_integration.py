"""
Integration test for skill run full pipeline with session saving and auto-skill creation.

This test exercises the complete end-to-end flow:
1. Run skill run with a complex goal that chains skills and a raw task
2. Verify router.session.yaml is written to workdir
3. Verify pipeline-summary.txt is created by the raw task
4. Auto-create a skill from the router session
5. Verify the new skill is valid and executable with --dry-run

Run with: pytest tests/test_skill_run_integration.py -m llm -s -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))

pytestmark = pytest.mark.llm


@pytest.fixture(autouse=True)
def cleanup_created_skills(skills_dir):
    """Snapshot skills_dir before test, remove any created skills after."""
    before = set(skills_dir.iterdir())
    yield
    after = set(skills_dir.iterdir())
    new_dirs = after - before
    for d in new_dirs:
        if d.is_dir():
            shutil.rmtree(d)


def test_skill_run_full_pipeline(workdir, skills_dir):
    """
    Test full pipeline: skill run -> router.session.yaml -> auto-create skill -> verify skill.

    Steps:
    1. Run skill run with a goal that chains test-chain-a, test-chain-b, and a raw task
    2. Assert router.session.yaml exists and is valid
    3. Assert pipeline-summary.txt was created by the raw task
    4. Auto-create a skill from router.session.yaml
    5. Verify the new skill is executable with --dry-run
    """
    goal = (
        "First run test-chain-a with input='pipeline-test', then run test-chain-b "
        "using the output as chain_input, then use a raw task to write a file "
        "called 'pipeline-summary.txt' in the workdir summarizing the results"
    )

    skill_run_cmd = [
        "skill",
        "run",
        goal,
        "--workdir",
        str(workdir),
        "--max-iterations",
        "8",
        "--save-session",
        "--no-eval",
    ]

    print(f"\n=== COMMAND EXECUTED ===\n{' '.join(skill_run_cmd)}\n")

    print(">>> Running skill run command...", flush=True)

    import time

    start_time = time.time()

    result = subprocess.run(
        skill_run_cmd,
        capture_output=True,
        text=True,
        timeout=300,
        env=os.environ.copy(),
    )

    print(f"=== skill run output ===\n{result.stdout}")
    if result.stderr:
        print(f"=== skill run stderr ===\n{result.stderr}")

    # Debug: print workdir contents
    print(f"\n=== WORKDIR CONTENTS ===")
    for item in sorted(workdir.iterdir()):
        print(f"  {item.name}")
        if item.is_dir():
            for sub in sorted(item.iterdir()):
                print(f"    - {sub.name}")

    # Debug: check subdirs matching pattern
    subdirs_check = [d for d in workdir.iterdir() if d.is_dir() and d.name[0].isdigit()]
    print(f"\n=== SUBDIRS MATCHING NN_* ===")
    for sd in subdirs_check:
        print(f"  {sd.name}")
        sessions = list(sd.glob("*.session.yaml"))
        print(f"    session files: {[s.name for s in sessions]}")
        # Try to load the first session file
        if sessions:
            try:
                with open(sessions[0]) as f:
                    data = yaml.safe_load(f)
                print(
                    f"    loaded: turns={len(data.get('turns', []))}, exit_code={data.get('exit_code')}"
                )
            except Exception as e:
                print(f"    ERROR loading: {e}")

    # Check for shell errors that indicate tool execution problems
    if "/bin/sh:" in result.stderr and "Syntax error" in result.stderr:
        pytest.fail(
            f"Shell syntax error detected in stderr - indicates tool execution issue:\n{result.stderr}"
        )

    router_session_path = workdir / "router.session.yaml"
    assert router_session_path.exists(), (
        f"router.session.yaml not found in {workdir}. "
        f"Contents: {list(workdir.iterdir())}"
    )

    with open(router_session_path) as f:
        session_data = yaml.safe_load(f)

    assert session_data is not None, "router.session.yaml is empty"
    assert "task_description" in session_data, "Missing task_description in session"

    # Check if the router session indicates success
    router_exit_code = session_data.get("exit_code", 0)
    end_reason = session_data.get("end_reason", "")

    # Print this for debugging
    print(f"\n=== ROUTER SESSION STATUS ===")
    print(f"exit_code: {router_exit_code}")
    print(f"end_reason: {end_reason}")
    print(f"turns count: {len(session_data.get('turns', []))}")

    # The pipeline should have succeeded (exit_code == 0)
    # If exit_code != 0, it means the router didn't complete successfully
    if router_exit_code != 0:
        pytest.fail(
            f"Router session indicates failure: exit_code={router_exit_code}, end_reason={end_reason}.\n"
            f"This means the pipeline did not complete successfully.\n"
            f"session_data: {session_data}"
        )

    # Also check each subdir's session for failures
    for subdir in subdirs:
        session_files = list(subdir.glob("*.session.yaml"))
        for sf in session_files:
            with open(sf) as f:
                sub_session = yaml.safe_load(f)
            sub_exit_code = sub_session.get("exit_code", 0) if sub_session else 0
            sub_workdir = (
                sub_session.get("workdir", "unknown") if sub_session else "unknown"
            )
            print(f"=== Subdir {subdir.name} exit_code: {sub_exit_code} ===")
            if sub_exit_code != 0:
                pytest.fail(
                    f"Subdir {subdir.name} has exit_code={sub_exit_code}.\n"
                    f"workdir: {sub_workdir}\n"
                    f"This means the skill/task in this subdir failed."
                )

    subdirs = [d for d in workdir.iterdir() if d.is_dir() and d.name[0].isdigit()]
    assert len(subdirs) >= 2, (
        f"Expected at least 2 skill subdirs (NN_<name> pattern), "
        f"found {len(subdirs)}: {[d.name for d in subdirs]}"
    )

    for subdir in subdirs:
        session_files = list(subdir.glob("*.session.yaml"))
        assert len(session_files) >= 1, (
            f"Subdir {subdir.name} missing session file. "
            f"Contents: {list(subdir.iterdir())}"
        )
        print(f"=== Session file found: {subdir.name}/{session_files[0].name} ===")

    skill_subdirs = [d for d in subdirs if "_task" not in d.name]
    assert len(skill_subdirs) >= 1, (
        f"Expected at least 1 skill subdir, found: {[d.name for d in subdirs]}"
    )

    task_subdirs = [d for d in subdirs if "_task" in d.name]
    assert len(task_subdirs) >= 1, (
        f"Expected at least 1 task subdir (contains '_task'), "
        f"found: {[d.name for d in subdirs]}"
    )

    for task_dir in task_subdirs:
        task_sessions = list(task_dir.glob("*.session.yaml"))
        assert len(task_sessions) >= 1, (
            f"Task subdir {task_dir.name} missing session file. "
            f"Contents: {list(task_dir.iterdir())}"
        )

    summary_files = list(workdir.rglob("pipeline-summary.txt"))
    assert len(summary_files) >= 1, (
        f"pipeline-summary.txt not found anywhere under {workdir}. "
        f"Contents: {list(workdir.rglob('*'))}"
    )

    before = set(skills_dir.iterdir())

    from core import session_to_skill as sts_module
    import io
    from contextlib import redirect_stdout, redirect_stderr
    from unittest.mock import patch

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    generated_skill_name = None

    def mock_prompt_confirm(prompt_text, default=False):
        return True

    def mock_prompt_free_text(prompt_text):
        nonlocal generated_skill_name
        generated_skill_name = f"auto-skill-{workdir.name}"
        return generated_skill_name

    def mock_prompt_with_options(prompt_text, options, default=None):
        return "a"

    original_import = sts_module.__dict__.get("prompt_confirm")

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            sts_module.prompt_confirm = mock_prompt_confirm
            sts_module.prompt_free_text = mock_prompt_free_text
            sts_module.prompt_with_options = mock_prompt_with_options
            from core.session_to_skill import create_skill_from_session

            create_skill_from_session(router_session_path, skill_name=None)
        create_success = True
        create_stdout = stdout_capture.getvalue()
        create_stderr = stderr_capture.getvalue()
    except Exception as e:
        create_success = False
        create_stdout = stdout_capture.getvalue()
        create_stderr = stderr_capture.getvalue() + "\n" + str(e)
    finally:
        if original_import:
            sts_module.prompt_confirm = original_import

    print(f"=== skill create output ===\n{create_stdout}")
    if create_stderr:
        print(f"=== skill create stderr ===\n{create_stderr}")

    if not create_success:
        print(f"workdir: {workdir}")
        print(f"skills_dir: {skills_dir}")
        print(f"skills_dir contents: {list(skills_dir.iterdir())}")
        pytest.fail(f"skill create auto-from-session failed: {create_stderr}")

    after = set(skills_dir.iterdir())
    new_dirs = after - before
    assert len(new_dirs) == 1, (
        f"Expected exactly 1 new skill directory, found {len(new_dirs)}: "
        f"{[d.name for d in new_dirs]}"
    )

    new_skill_dir = list(new_dirs)[0]
    skill_md_path = new_skill_dir / "SKILL.md"
    assert skill_md_path.exists(), (
        f"SKILL.md not found in new skill dir {new_skill_dir}"
    )

    skill_content = skill_md_path.read_text()
    print(f"\n=== CREATED SKILL CONTENT ===\n{skill_content}\n")

    is_generic = (
        "Skill extracted from session" in skill_content
        and "body" not in skill_content.lower()
    )
    assert not is_generic, (
        f"Skill body is too generic - just a placeholder. "
        f"Content: {skill_content[:500]}"
    )

    assert len(skill_content) > 300, (
        f"Skill content suspiciously short ({len(skill_content)} chars). "
        f"Content: {skill_content}"
    )

    new_skill_name = new_skill_dir.name

    apply_result = subprocess.run(
        [
            "skill",
            "apply",
            new_skill_name,
            "--workdir",
            str(workdir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    print(f"=== skill apply --dry-run output ===\n{apply_result.stdout}")
    if apply_result.stderr:
        print(f"=== skill apply --dry-run stderr ===\n{apply_result.stderr}")

    assert apply_result.returncode == 0, (
        f"skill apply --dry-run failed with exit code {apply_result.returncode}. "
        f"stdout: {apply_result.stdout}, stderr: {apply_result.stderr}"
    )
