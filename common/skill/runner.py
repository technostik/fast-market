from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from common import structlog
from common.core.paths import get_skills_dir
from common.skill.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)


@dataclass
class SkillResult:
    skill_name: str
    script_name: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def resolve_skill_script(skill_ref: str) -> tuple[Skill, Path] | tuple[None, None] | tuple[Skill, None]:
    """
    Resolve 'skillname' or 'skillname/scriptname' to (Skill, script_path).

    Resolution order for script_name when not specified:
    1. If scripts/ has exactly one file -> use it
    2. Otherwise -> scripts/run.sh

    Returns (None, None) if skill not found.
    Returns (skill, None) if skill found but no script.
    """
    ref = (skill_ref or "").strip().split()[0] if skill_ref else ""
    if not ref:
        return None, None

    skill_name, script_name = (ref.split("/", 1) + [None])[:2] if "/" in ref else (ref, None)

    skills = discover_skills(get_skills_dir())
    skill = next((s for s in skills if s.name == skill_name), None)
    if not skill:
        return None, None

    scripts_dir = skill.path / "scripts"
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return skill, None

    if script_name:
        script_path = scripts_dir / script_name
        return (skill, script_path) if script_path.exists() else (skill, None)

    script_files = [p for p in sorted(scripts_dir.iterdir()) if p.is_file()]
    if len(script_files) == 1:
        return skill, script_files[0]

    default_script = scripts_dir / "run.sh"
    if default_script.exists():
        return skill, default_script

    return skill, None


def execute_skill_script(
    skill_ref: str,
    workdir: Path,
    params: dict[str, str] | None = None,
    timeout: int = 60,
) -> SkillResult:
    """Execute a skill script directly with SKILL_* environment parameters."""
    resolved = (skill_ref or "").strip().split()[0] if skill_ref else ""
    ref_skill_name = resolved.split("/", 1)[0] if resolved else ""
    skill, script_path = resolve_skill_script(skill_ref)

    if skill is None:
        return SkillResult(
            skill_name=ref_skill_name,
            script_name="",
            stdout="",
            stderr=f"Skill not found: {ref_skill_name}",
            exit_code=127,
        )

    if script_path is None:
        return SkillResult(
            skill_name=skill.name,
            script_name="",
            stdout="",
            stderr=(
                f"No script found for skill '{skill.name}'. "
                "Expected scripts/run.sh or a single file under scripts/."
            ),
            exit_code=127,
        )

    if not script_path.exists() or not script_path.is_file():
        return SkillResult(
            skill_name=skill.name,
            script_name=script_path.name,
            stdout="",
            stderr=f"Skill script not found: {script_path}",
            exit_code=127,
        )

    if not os.access(script_path, os.X_OK):
        return SkillResult(
            skill_name=skill.name,
            script_name=script_path.name,
            stdout="",
            stderr=f"Skill script is not executable: {script_path}. Try: chmod +x '{script_path}'",
            exit_code=126,
        )

    env = os.environ.copy()
    for key, value in (params or {}).items():
        env[f"SKILL_{str(key).upper()}"] = str(value)

    logger.debug(
        "executing skill script",
        skill=skill.name,
        script=str(script_path),
        workdir=str(workdir),
        timeout=timeout,
    )

    try:
        result = subprocess.run(
            [str(script_path)],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return SkillResult(
            skill_name=skill.name,
            script_name=script_path.name,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return SkillResult(
            skill_name=skill.name,
            script_name=script_path.name,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") or f"Skill script timed out after {timeout} seconds",
            exit_code=124,
            timed_out=True,
        )


def execute_skill_run(
    skill: Skill,
    workdir: Path,
    params: dict[str, str] | None = None,
    timeout: int = 60,
) -> SkillResult:
    """
    Execute the skill's run: frontmatter command.

    Supports {param} substitution and SKILL_* environment variables.
    """
    cmd = skill.run
    for key, value in (params or {}).items():
        cmd = cmd.replace(f"{{{key}}}", str(value))

    unresolved = sorted(set(re.findall(r"\{(\w+)\}", cmd)))
    if unresolved:
        return SkillResult(
            skill_name=skill.name,
            script_name="run:",
            stdout="",
            stderr=(
                f"Unresolved parameters: {', '.join(unresolved)}. "
                "Pass them as KEY=VALUE arguments."
            ),
            exit_code=1,
        )

    env = os.environ.copy()
    for key, value in (params or {}).items():
        env[f"SKILL_{str(key).upper()}"] = str(value)

    logger.debug(
        "executing skill run command",
        skill=skill.name,
        command=cmd,
        workdir=str(workdir),
        timeout=timeout,
    )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workdir,
            env=env,
            capture_output=False,
            timeout=timeout,
        )
        return SkillResult(
            skill_name=skill.name,
            script_name="run:",
            stdout="",
            stderr="",
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            skill_name=skill.name,
            script_name="run:",
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            exit_code=124,
            timed_out=True,
        )


def execute_skill_prompt(
    skill: Skill,
    workdir: Path,
    params: dict[str, str] | None = None,
    timeout: int = 300,
    provider: str | None = None,
    model: str | None = None,
    save_session: Path | None = None,
) -> SkillResult:
    """
    Execute skill body as a task description via `task apply`.
    """
    body = skill.get_body()
    for key, value in (params or {}).items():
        body = body.replace(f"{{{key}}}", str(value))

    learn_path = skill.path / "LEARN.md"
    if learn_path.exists():
        learn_content = learn_path.read_text(encoding="utf-8")
        body = f"{body}\n\n---\n## Lessons from previous runs\n{learn_content}"

    cmd = ["task", "apply", body]
    if provider:
        cmd += ["-P", provider]
    if model:
        cmd += ["-m", model]
    for key, value in (params or {}).items():
        cmd += ["--param", f"{key}={value}"]
    if workdir and str(workdir) != ".":
        cmd += ["--workdir", str(workdir)]
    if save_session:
        cmd += ["--save-session", str(save_session)]

    logger.debug("executing_skill_prompt", skill=skill.name, cmd=cmd)

    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            timeout=timeout,
        )
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr="",
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr=f"Task timed out after {timeout}s",
            exit_code=124,
            timed_out=True,
        )
    except FileNotFoundError:
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr="'task' command not found. Is task-cli installed?",
            exit_code=127,
        )
