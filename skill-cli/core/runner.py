from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from uuid import uuid4

from common import structlog
from common.core.config import load_tool_config
from common.core.paths import get_skills_dir
from common.core.yaml_utils import dump_yaml
from core.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)


def make_run_root(workdir: Path, skill_name: str | None = None) -> Path:
    """Create a unique isolated subdirectory inside workdir.

    Returns the created path: {workdir}/{skill_name}_{uuid6}/
    or {workdir}/{timestamp}_{uuid6}/ if skill_name is not provided.
    """
    unique_id = uuid4().hex[:6]
    if skill_name:
        run_id = f"{skill_name}_{unique_id}"
    else:
        run_id = dt.utcnow().strftime("%Y%m%dT%H%M%S") + "_" + unique_id
    run_root = workdir / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    logger.info("created_run_root", run_root=str(run_root), run_id=run_id)
    return run_root


def _write_script_session(
    skill_name: str,
    script_name: str,
    params: dict,
    stdout: str,
    stderr: str,
    exit_code: int,
    save_path: Path,
) -> None:
    """Write an artificial session.yaml for script skills."""
    import yaml
    from datetime import datetime, timezone

    session_data = {
        "task_description": f"Skill: {skill_name}",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "end_reason": "completed" if exit_code == 0 else "failed",
        "metrics": {
            "total_tool_calls": 1,
            "error_count": 1 if exit_code != 0 else 0,
        },
        "turns": [
            {
                "role": "assistant",
                "content": f"Run skill script: {skill_name}/{script_name}",
                "tool_calls": [
                    {
                        "name": "script_execution",
                        "arguments": {
                            "skill": skill_name,
                            "script": script_name,
                            "params": params,
                            "command": f"{skill_name}/{script_name}",
                        },
                        "stdout": stdout,
                        "error": stderr if exit_code != 0 else None,
                        "exit_code": exit_code,
                    }
                ],
            }
        ],
    }

    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "w") as f:
        yaml.dump(session_data, f, default_flow_style=False, sort_keys=False)
    logger.info("script_session_written", path=str(save_path), skill=skill_name)


@dataclass
class SkillResult:
    skill_name: str
    script_name: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def resolve_skill_script(
    skill_ref: str,
) -> tuple[Skill, Path] | tuple[None, None] | tuple[Skill, None]:
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

    skill_name, script_name = (
        (ref.split("/", 1) + [None])[:2] if "/" in ref else (ref, None)
    )

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
    timeout: int | None = None,
    save_session: Path | None = None,
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

    effective_timeout = timeout if timeout is not None else skill.timeout
    if effective_timeout is None:
        effective_timeout = 60
    effective_timeout = int(str(effective_timeout).rstrip("s"))
    if effective_timeout == 0:
        effective_timeout = None  # 0 means no timeout

    logger.debug(
        "executing skill script",
        skill=skill.name,
        script=str(script_path),
        workdir=str(workdir),
        timeout=effective_timeout,
    )

    try:
        result = subprocess.run(
            [str(script_path)],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=effective_timeout if effective_timeout else None,
        )

        # Write artificial session file for script skills when requested
        if save_session:
            _write_script_session(
                skill_name=skill.name,
                script_name=script_path.name,
                params=params or {},
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                save_path=save_session,
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
            stderr=(exc.stderr or "")
            or f"Skill script timed out after {effective_timeout} seconds",
            exit_code=124,
            timed_out=True,
        )


def execute_skill_run(
    skill: Skill,
    workdir: Path,
    params: dict[str, str] | None = None,
    timeout: int | None = None,
    save_session: Path | None = None,
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

    effective_timeout = timeout if timeout is not None else skill.timeout
    if effective_timeout is None:
        effective_timeout = 60
    effective_timeout = int(str(effective_timeout).rstrip("s"))
    if effective_timeout == 0:
        effective_timeout = None  # 0 means no timeout

    logger.debug(
        "executing skill run command",
        skill=skill.name,
        command=cmd,
        workdir=str(workdir),
        timeout=effective_timeout,
    )

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=effective_timeout if effective_timeout else None,
        )

        # Write artificial session file for run: skills when requested
        if save_session:
            _write_script_session(
                skill_name=skill.name,
                script_name="run:",
                params=params or {},
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                save_path=save_session,
            )

        return SkillResult(
            skill_name=skill.name,
            script_name="run:",
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return SkillResult(
            skill_name=skill.name,
            script_name="run:",
            stdout="",
            stderr=f"Skill run timed out after {effective_timeout}s",
            exit_code=124,
            timed_out=True,
        )


def execute_skill_prompt(
    skill: Skill,
    workdir: Path,
    params: dict[str, str] | None = None,
    timeout: int | None = None,
    max_iterations: int | None = None,
    llm_timeout: int | None = None,
    auto_learn: bool = False,
    provider: str | None = None,
    model: str | None = None,
    save_session: Path | None = None,
    compact: bool = False,
    verbose: bool = False,
    debug: str | None = None,
    shared_context=None,  # SharedContext instance
    global_goal: str = "",
    inject: str | None = None,
) -> SkillResult:
    """Execute skill body as a task description via common/agent TaskLoop."""
    from functools import partial
    from common.agent.loop import TaskConfig, TaskLoop
    from common.agent.executor import resolve_and_execute_command
    from common.core.config import load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name

    original_body = skill.get_body()
    body = original_body
    consumed_params: set[str] = set()
    for key, value in (params or {}).items():
        placeholder = f"{{{key}}}"
        if placeholder in body:
            body = body.replace(placeholder, str(value))
            consumed_params.add(key)

    unconsumed = {k: v for k, v in (params or {}).items() if k not in consumed_params}
    if unconsumed:
        lines = ["\n\n## Task Parameters"]
        for key in sorted(unconsumed):
            lines.append(f"- {key}: {unconsumed[key]}")
        body = body + "\n".join(lines)

    learn_path = skill.path / "LEARN.md"
    if learn_path.exists():
        learn_content = learn_path.read_text(encoding="utf-8")
        body = f"{body}\n\n---\n## Lessons from previous runs\n{learn_content}"

    if skill.stop_condition:
        body = f"{body}\n\n---\n## Completion Criteria\n{skill.stop_condition}"

    # Inject additional instructions if provided
    if inject:
        body = f"{body}\n\n---\n## Additional Instructions\n{inject}"

    # Inject shared context information
    if shared_context is not None:
        context_content = shared_context.read()
        context_section = "\n\n---\n## Shared Context\n"
        context_section += f"**Global task**: {global_goal}\n\n"
        if context_content:
            context_section += f"**Current context state**:\n{context_content}\n\n"
        else:
            context_section += "**Current context state**: (empty)\n\n"
        context_section += (
            "You can read/write the shared context using the `shared_context` tool.\n"
            "- Use `shared_context(action='read')` to see current state\n"
            "- Use `shared_context(action='write', content='...')` to replace the context\n"
            "- Use `shared_context(action='append', content='...')` to add to the context\n"
            "- Use `shared_context(action='clear')` to reset the context\n\n"
            "**Instructions**: Write key results, extracted data, or intermediate outputs to the shared context "
            "so downstream skills can use them. Read the context to understand what previous steps produced."
        )
        body = body + context_section

    effective_timeout = timeout if timeout is not None else skill.timeout
    if effective_timeout is None:
        effective_timeout = 300
    effective_timeout = int(str(effective_timeout).rstrip("s"))
    if effective_timeout == 0:
        effective_timeout = None

    effective_max_iterations = (
        max_iterations if max_iterations is not None else skill.max_iterations
    )

    effective_llm_timeout = (
        llm_timeout if llm_timeout is not None else skill.llm_timeout
    )
    if effective_llm_timeout is None:
        effective_llm_timeout = 0

    from commands.setup import init_skill_agent_config

    task_config_dict = init_skill_agent_config()

    fastmarket_tools = task_config_dict.get("fastmarket_tools", {})
    system_commands = task_config_dict.get("system_commands", [])
    allowed_commands = list(fastmarket_tools.keys()) + system_commands
    command_docs = task_config_dict.get("command_docs")
    agent_prompt = task_config_dict.get("agent_prompt")

    try:
        config = load_tool_config("apply")
        providers = discover_providers(config)
        provider_name = provider or get_default_provider_name(config)
    except Exception as exc:
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr=f"Failed to load LLM config: {exc}",
            exit_code=1,
        )

    if provider_name not in providers:
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr=f"LLM provider '{provider_name}' not available",
            exit_code=1,
        )

    task_config = TaskConfig(
        fastmarket_tools=fastmarket_tools,
        system_commands=system_commands,
        allowed_commands=allowed_commands,
        max_iterations=effective_max_iterations
        or task_config_dict.get("max_iterations", 20),
        default_timeout=task_config_dict.get("default_timeout", 60),
        llm_timeout=effective_llm_timeout,
        temperature=config.get("default_temperature", 0.3),
        command_docs=command_docs,
        agent_prompt=agent_prompt,
    )

    if debug:
        from common.llm.base import set_llm_log_file

        log_path = workdir / "llm.log"
        set_llm_log_file(log_path)
        logger.info("llm_log_enabled", path=str(log_path))

    loop = TaskLoop(
        config=task_config,
        workdir=workdir,
        provider=provider_name,
        model=model,
        silent=not verbose,
        debug=debug or "",
        shared_context=shared_context,
    )

    execute_fn = partial(
        resolve_and_execute_command,
        workdir=workdir,
        allowed=set(task_config.allowed_commands),
        timeout=task_config.default_timeout,
        env_params=params,
    )

    try:
        loop.run(
            body,
            execute_fn,
            task_params=params or {},
        )

        if save_session and loop.session:
            from datetime import datetime

            loop.session.end_time = datetime.utcnow()
            loop.session.save(save_session)

        end_reason = getattr(loop.session, "end_reason", "") or ""
        exit_code = 0 if "success" in end_reason else 1

        stdout_parts = []
        stderr_parts = []
        if loop.session:
            for turn in loop.session.turns:
                for tc in turn.tool_calls:
                    if tc.stdout:
                        stdout_parts.append(tc.stdout)
                    if tc.stderr:
                        stderr_parts.append(tc.stderr)

        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="\n".join(stdout_parts),
            stderr="\n".join(stderr_parts),
            exit_code=exit_code,
            timed_out=False,
        )

    except Exception as exc:
        logger.error("execute_skill_prompt_failed", skill=skill.name, error=str(exc))
        if save_session and loop.session:
            from datetime import datetime

            loop.session.exit_code = 1
            loop.session.error = str(exc)
            loop.session.end_reason = f"internal failure: {exc}"
            loop.session.end_time = datetime.utcnow()
            loop.session.save(save_session)
        return SkillResult(
            skill_name=skill.name,
            script_name="prompt:",
            stdout="",
            stderr=str(exc),
            exit_code=1,
            timed_out=False,
        )


def _run_auto_learn_from_skill(
    skill: Skill,
    params: dict[str, str] | None,
    workdir: Path,
    timed_out: bool = False,
    timed_out_seconds: int = 300,
    provider=None,
    model: str | None = None,
    session=None,
    session_path: Path | None = None,
) -> None:
    """Run auto-learn for a skill using LLM."""
    from datetime import datetime
    import yaml
    from common.learn import (
        analyze_session,
        update_learn_file,
        get_learn_analysis_prompt,
        get_learn_result_template,
    )

    learn_path = skill.path / "LEARN.md"

    if timed_out and session is None:
        timestamp = datetime.utcnow().isoformat()
        content = f"""# Lessons Learned for {skill.name}

## What to Avoid
- Task timed out after {timed_out_seconds}s — consider increasing timeout or simplifying the task

## Common Errors and Fixes
- Error: Task timeout → Fix: Increase --timeout value or reduce task complexity
"""
        existing = ""
        if learn_path.exists():
            existing = learn_path.read_text(encoding="utf-8")

        stamped = f"---\n<!-- auto-learn: {timestamp} (timeout) -->\n\n{content}"
        merged = (existing.rstrip() + "\n\n" + stamped).strip() + "\n"

        learn_path.write_text(merged, encoding="utf-8")
        logger.info(
            "auto_learn_timeout", skill=skill.name, timeout_seconds=timed_out_seconds
        )
    elif provider is not None:
        try:
            from common.core.config import resolve_llm_config
            from common.learn import (
                get_learn_analysis_prompt,
                get_learn_result_template,
            )

            config = resolve_llm_config("skill")
            learn_analysis_prompt = get_learn_analysis_prompt(config)
            learn_result_template = get_learn_result_template(config)

            existing_learn_content = None
            if learn_path.exists():
                existing_learn_content = learn_path.read_text(encoding="utf-8")

            content, prompt = analyze_session(
                session,
                skill.name,
                provider,
                model,
                learn_analysis_prompt=learn_analysis_prompt,
                learn_result_template=learn_result_template,
                existing_learn_content=existing_learn_content,
                temperature=config.get("default_temperature"),
            )
            update_learn_file(
                skill.name,
                content,
                merge=True,
                provider=provider,
                model=model,
                temperature=config.get("default_temperature"),
            )

            if session_path and session_path.exists():
                session_data = yaml.safe_load(session_path.read_text()) or {}
                learning_section = {
                    "learning": {
                        "prompt": prompt,
                        "result": content,
                    }
                }
                session_data["learning"] = learning_section["learning"]
                session_path.write_text(
                    dump_yaml(session_data, sort_keys=False),
                    encoding="utf-8",
                )

            logger.info("auto_learn_success", skill=skill.name)
        except Exception as exc:
            logger.warning("auto_learn_failed", skill=skill.name, error=str(exc))
