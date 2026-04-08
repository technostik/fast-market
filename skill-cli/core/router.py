from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from functools import partial
from typing import Any

import click

from common import structlog
from common.agent.loop import TaskConfig, TaskLoop
from common.agent.executor import resolve_and_execute_command
from common.agent.prompts import (
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
)
from common.core.paths import get_skills_dir
from common.llm.base import LLMRequest
from core.runner import make_run_root
from core.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLAN_PROMPT = DEFAULT_PLAN_PROMPT
PREPARATION_PROMPT = DEFAULT_PREPARATION_PROMPT
EVALUATION_PROMPT = DEFAULT_EVALUATION_PROMPT

RUNNER_SUMMARY_PROMPT = """Write a concise summary (max 15 lines) for the orchestrator:
- Did it succeed or fail? Use EXIT CODE of the LAST command: exit code 0 = success, non-zero = failure
- What approach was used?
- What errors occurred and what is the root cause?
- What alternative approaches could work if this failed?
- What files or outputs were produced (names only, not contents)?
Do NOT include file contents or large data.

## Skill/task executed
{skill_name} with params: {params}

## Session output
{session_output}
"""

CONTEXT_EXTRACT_PROMPT = """You are preparing context for the NEXT step in a pipeline.

## Goal of the overall task
{goal}

## Step just executed
{skill_name} with params: {params}

## Session output
{session_output}

## What the next step will likely need
{next_step_hint}

Extract ONLY what a downstream step will need to do its job.
Include: key data, results, extracted content, file contents if small (<200 lines).
For large files: include the first 50 lines and note the full path.
Be specific. No meta-commentary.
"""

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillAttempt:
    action: str  # "run", "task", "ask"
    skill_name: str  # skill name, "(task)", or "(user)"
    params: dict[str, str]
    exit_code: int
    runner_summary: str
    context: str
    context_hint: str
    success: bool
    iteration: int
    subdir: Path
    raw_output: str = ""  # raw stdout/stderr from skill execution
    internal_steps: int = 0  # TaskLoop turns within this attempt


@dataclass
class SkillPlanStep:
    """A single step in a skill execution plan."""
    step: int
    action: str  # "run", "task", "ask"
    skill_name: str = ""  # for action="run"
    params: dict[str, str] = None  # for action="run"
    inject: str = ""  # injected instructions for action="run"
    description: str = ""  # for action="task"
    instructions: str = ""  # additional instructions for action="task"
    question: str = ""  # for action="ask"
    context_hint: str = ""  # hint about context needed
    name: str = ""  # task name, used by run-plan convert-task-to-skill
    original_description: str = ""  # original description before placeholder substitution
    original_params: dict[str, str] = None  # original params from plan before substitution


@dataclass
class SkillPlan:
    """A complete execution plan exported from the router."""
    goal: str
    steps: list[SkillPlanStep] = None
    success_criteria: str = ""
    preparation_plan: str = ""


@dataclass
class SkillExecutionLog:
    """A log of actual skill executions during a run."""
    goal: str
    attempts: list[dict] = None  # simplified attempt info
    start_time: str = ""
    end_time: str = ""
    status: str = ""  # "completed", "failed", "max_iterations"
    final_result: str = ""
    failure_reason: str = ""


@dataclass
class PreparationResult:
    plan: str
    success_criteria: str
    risks: str


@dataclass
class EvaluationResult:
    satisfied: bool
    reason: str
    suggestion: str


@dataclass
class RouterState:
    goal: str
    attempts: list[SkillAttempt]
    iteration: int
    max_iterations: int
    done: bool = False
    final_result: str = ""
    failed: bool = False
    failure_reason: str = ""
    success_criteria: str = ""
    preparation: str = ""
    run_root: Path | None = None
    isolation_mode: str = "skill"  # "none", "run", or "skill"
    shared_context: Any = None  # SharedContext instance or None
    imported_plan: SkillPlan | None = None  # imported plan if provided
    exported_plan_path: Path | None = None  # where to export the plan
    export_execution_path: Path | None = None  # where to export execution log
    start_time: float = 0.0  # timestamp when run started
    end_time: float = 0.0  # timestamp when run completed


# ---------------------------------------------------------------------------
# Interaction plugin
# ---------------------------------------------------------------------------


class InteractionPlugin:
    def ask(self, question: str) -> str:
        raise NotImplementedError


class CLIInteractionPlugin(InteractionPlugin):
    def ask(self, question: str) -> str:
        print(f"\n[router] Question for you:\n  {question}")
        try:
            return input("Your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""


# ---------------------------------------------------------------------------
# Interactive approval plugin
# ---------------------------------------------------------------------------


@dataclass
class ApprovalResult:
    """Result of an interactive step approval."""
    action: str  # "accept", "skip", "edit", "replan", "quit"
    modified_plan: dict | None = None


class InteractiveApprovalPlugin:
    """Prompts user for approval before each step execution."""

    def approve(self, plan: dict, history: list[SkillAttempt]) -> ApprovalResult:
        action = plan.get("action", "unknown")

        click.echo(f"\n{'=' * 60}")
        click.echo(f"Next step: {action.upper()}")
        click.echo(f"{'=' * 60}")

        if action == "run":
            click.echo(f"  Skill: {plan.get('skill_name')}")
            if plan.get("params"):
                for k, v in plan["params"].items():
                    click.echo(f"  {k}: {v}")
            if plan.get("inject"):
                click.echo(f"  Inject: {plan['inject'][:80]}{'...' if len(plan['inject']) > 80 else ''}")
        elif action == "task":
            desc = plan.get("description", "")
            click.echo(f"  {desc[:100]}{'...' if len(desc) > 100 else ''}")
            if plan.get("instructions"):
                click.echo(f"  Instructions: {plan['instructions'][:80]}{'...' if len(plan['instructions']) > 80 else ''}")
        elif action == "ask":
            click.echo(f"  Question: {plan.get('question', '')}")

        if plan.get("context_hint"):
            click.echo(f"  Context: {plan['context_hint'][:80]}{'...' if len(plan['context_hint']) > 80 else ''}")

        if plan.get("reason"):
            click.echo(f"  Reason: {plan['reason'][:80]}{'...' if len(plan['reason']) > 80 else ''}")

        click.echo()

        from core.repl import prompt_with_options, prompt_free_text
        from common.cli.helpers import open_editor
        import tempfile
        import yaml as yaml_lib

        choice = prompt_with_options(
            "Action — [A]ccept / [S]kip / [E]dit / [R]eplan / [Q]uit: ",
            ["a", "s", "e", "r", "q"],
            default="a",
        )

        if choice == "q":
            return ApprovalResult(action="quit")
        elif choice == "s":
            return ApprovalResult(action="skip")
        elif choice == "r":
            return ApprovalResult(action="replan")
        elif choice == "e":
            # Open plan dict in editor
            editable = {k: v for k, v in plan.items()}
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                yaml_lib.dump(editable, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                temp_path = Path(f.name)

            try:
                import subprocess
                open_editor(temp_path)
                modified = yaml_lib.safe_load(temp_path.read_text())
                if not isinstance(modified, dict) or "action" not in modified:
                    click.echo("Error: invalid YAML. Keeping original.", err=True)
                    return ApprovalResult(action="accept")
                return ApprovalResult(action="accept", modified_plan=modified)
            except subprocess.CalledProcessError:
                click.echo("Editor error. Keeping original.", err=True)
                return ApprovalResult(action="accept")
            except Exception as e:
                click.echo(f"Error: {e}. Keeping original.", err=True)
                return ApprovalResult(action="accept")
            finally:
                temp_path.unlink(missing_ok=True)

        return ApprovalResult(action="accept")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _repair_json(s: str) -> str:
    """Strip markdown fences and extract the first JSON object found."""
    if not s:
        return s
    if "```" in s:
        s = s.replace("```json", "```")
        parts = [p.strip() for p in s.split("```") if p.strip()]
        candidates = [
            p for p in parts if p.lstrip().startswith("{") and p.rstrip().endswith("}")
        ]
        if candidates:
            return candidates[0].lstrip()
        for p in parts:
            if "{" in p and "}" in p:
                start, end = p.find("{"), p.rfind("}")
                if start != -1 and end > start:
                    return p[start : end + 1]
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            return s[start : end + 1]
    return s


def _parse_llm_json(raw: str, context: str = "LLM") -> dict:
    """Parse JSON from LLM response. Raises ValueError on failure."""
    if not raw:
        raise ValueError(f"{context} returned empty response")
    cleaned = _repair_json(raw)
    if not cleaned:
        raise ValueError(f"{context} returned unparseable response: {raw[:200]!r}")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{context} returned invalid JSON: {cleaned[:200]!r}. Error: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{context} returned non-object JSON: {type(data)}")
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_skills_list(skills: list[Skill]) -> str:
    parts = []
    for skill in skills:
        lines = [f"### {skill.name}", f"Description: {skill.description}"]
        if skill.parameters:
            param_names = ", ".join(
                p["name"] + (" (required)" if p.get("required") else "")
                for p in skill.parameters
                if "name" in p
            )
            if param_names:
                lines.append(f"Parameters: {param_names}")
        body = skill.get_body()
        if body:
            preview = body[:300] + ("..." if len(body) > 300 else "")
            lines.append(f"Instructions preview: {preview}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_history(attempts: list[SkillAttempt]) -> str:
    if not attempts:
        return "No steps executed yet."
    lines = []
    for a in attempts:
        status = "✓ success" if a.success else "✗ failed"
        params_str = ", ".join(f"{k}={v}" for k, v in a.params.items())
        lines.append(
            f"Step {a.iteration} [{a.action}]: {a.skill_name}({params_str}) → {status}"
        )
        lines.append(f"  Summary: {a.runner_summary[:300]}")
        if a.context:
            lines.append(f"  Context available: yes ({len(a.context)} chars)")
    return "\n".join(lines)


def _make_subdir(run_root: Path, iteration: int, label: str, isolation_mode: str = "skill") -> Path:
    """Create a subdirectory for a skill/task execution.

    isolation_mode:
    - "none": return empty Path (use workdir directly)
    - "run": return run_root (all skills share the same dir)
    - "skill": create and return a unique subdir per skill (current behavior)
    """
    if isolation_mode == "none":
        return Path("")
    if isolation_mode == "run":
        return run_root
    # isolation_mode == "skill"
    name = f"{iteration:02d}_{label}"
    subdir = run_root / name
    subdir.mkdir(parents=True, exist_ok=True)
    logger.info("created_subdir", subdir=str(subdir), iteration=iteration)
    return subdir


def _print_attempt(attempt: SkillAttempt) -> None:
    status = "success" if attempt.success else "failed"
    params = ", ".join(f"{k}={v}" for k, v in attempt.params.items())
    subdir_name = (
        attempt.subdir.name if attempt.subdir and attempt.subdir != Path("") else "N/A"
    )
    print(
        f"[router] step {attempt.iteration} [{attempt.action}]: {attempt.skill_name}({params}) -> {status}"
    )
    print(f"[router] subdir: {subdir_name}")
    print(f"[router] summary: {attempt.runner_summary[:300]}")


# ---------------------------------------------------------------------------
# LLM calls — all pure JSON, no tool calls
# ---------------------------------------------------------------------------


def _call_plan(
    state: RouterState,
    provider,
    model: str | None,
    skills: list[Skill],
    prompt_template: str | None = None,
    extra_context: str | None = None,
) -> dict:
    """Ask the planner what to do next. Returns dict with 'action' key."""
    template = prompt_template or PLAN_PROMPT
    prompt = template.format(
        goal=state.goal,
        skills_list=build_skills_list(skills),
        history=_format_history(state.attempts),
        success_criteria=state.success_criteria,
    )
    if extra_context:
        prompt += f"\n\n{extra_context}"
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=4096)
    response = provider.complete(req)
    raw = (response.content or "").strip()
    if not raw:
        raise ValueError(f"Planner returned empty response. Model: {response.model}.")
    return _parse_llm_json(raw, context="Planner")


def _call_runner_summary(
    label: str,
    params: dict,
    session_output: str,
    provider,
    model: str | None,
) -> str:
    prompt = RUNNER_SUMMARY_PROMPT.format(
        skill_name=label,
        params=params,
        session_output=session_output[:4000],
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=4096)
    response = provider.complete(req)
    summary = (response.content or "").strip()
    return summary or (session_output[:1000] if session_output else "(no summary)")


def _call_context_extract(
    goal: str,
    label: str,
    params: dict,
    session_output: str,
    next_step_hint: str,
    provider,
    model: str | None,
) -> str:
    prompt = CONTEXT_EXTRACT_PROMPT.format(
        goal=goal,
        skill_name=label,
        params=params,
        session_output=session_output[:5000],
        next_step_hint=next_step_hint
        or "Extract any useful data or results for the next step.",
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=4096)
    response = provider.complete(req)
    return (response.content or "").strip()


def _call_preparation(
    goal: str,
    provider,
    model: str | None,
    skills: list[Skill],
    prompt_template: str | None = None,
) -> PreparationResult:
    template = prompt_template or PREPARATION_PROMPT
    prompt = template.format(goal=goal, skills_list=build_skills_list(skills))
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=4096)
    response = provider.complete(req)
    raw = (response.content or "").strip()
    if not raw:
        raise ValueError(
            f"Preparation returned empty response. Model: {response.model}."
        )
    data = _parse_llm_json(raw, context="Preparation")
    return PreparationResult(
        plan=data.get("plan", ""),
        success_criteria=data.get("success_criteria", "Goal achieved"),
        risks=data.get("risks", ""),
    )


def _call_evaluation(
    state: RouterState,
    last_summary: str,
    success_criteria: str,
    provider,
    model: str | None,
    prompt_template: str | None = None,
) -> EvaluationResult:
    template = prompt_template or EVALUATION_PROMPT
    prompt = template.format(
        goal=state.goal,
        success_criteria=success_criteria,
        history=_format_history(state.attempts),
        last_summary=last_summary,
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=4096)
    response = provider.complete(req)
    raw = (response.content or "").strip()
    if not raw:
        raise ValueError(
            f"Evaluation returned empty response. Model: {response.model}."
        )
    data = _parse_llm_json(raw, context="Evaluation")
    return EvaluationResult(
        satisfied=bool(data.get("satisfied", False)),
        reason=data.get("reason", ""),
        suggestion=data.get("suggestion", ""),
    )


# ---------------------------------------------------------------------------
def _load_tools_description_simple(agent_config: dict) -> str:
    lines = []
    fastmarket_tools = agent_config.get("fastmarket_tools", {})
    if fastmarket_tools:
        lines.append("## Available Tools")
        for tool_name, tool_info in fastmarket_tools.items():
            desc = tool_info.get("description", "") if isinstance(tool_info, dict) else ""
            lines.append(f"- {tool_name}: {desc}")
    return "\n".join(lines) or "(no tools available)"


def _load_existing_skills_simple() -> str:
    try:
        skills = discover_skills(get_skills_dir())
        lines = []
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description or ''}")
        return "\n".join(lines) or "(no existing skills)"
    except Exception:
        return "(no existing skills)"


# ---------------------------------------------------------------------------
# Skill executor — delegates to runner.py, no TaskLoop duplication
# ---------------------------------------------------------------------------


def _run_skill(
    skill: Skill,
    params: dict[str, str],
    subdir: Path,
    provider_name: str,
    model: str | None,
    auto_learn: bool,
    compact: bool,
    prev_context: str,
    save_session: bool = False,
    shared_context=None,  # SharedContext instance
    global_goal: str = "",
    inject: str | None = None,  # Injected instructions
) -> tuple[int, str, Path | None, int]:
    """Execute a skill using the same dispatch as `skill apply`.

    Returns (exit_code, session_output_text, session_path, internal_steps).
    Delegates to runner.py — script/run:/prompt dispatch is not duplicated here.
    """
    from core.runner import (
        execute_skill_prompt,
        execute_skill_run,
        execute_skill_script,
    )

    # Inject router context so prompt skills can see previous step output
    effective_params = dict(params)
    if prev_context:
        effective_params["_router_context"] = prev_context

    session_path = None
    internal_steps = 0

    if skill.has_scripts:
        if save_session:
            session_path = subdir / f"{skill.name}.session.yaml"
        result = execute_skill_script(
            skill_ref=skill.name,
            workdir=subdir,
            params=effective_params,
            save_session=session_path,
        )
        session_output = (result.stdout or "") + (result.stderr or "")
        exit_code = result.exit_code
        internal_steps = result.internal_steps

    elif skill.run:
        if save_session:
            session_path = subdir / f"{skill.name}.session.yaml"
        result = execute_skill_run(
            skill=skill,
            workdir=subdir,
            params=effective_params,
            save_session=session_path,
        )
        session_output = (result.stdout or "") + (result.stderr or "")
        exit_code = result.exit_code
        internal_steps = result.internal_steps

    else:
        # Prompt skill — session file lives inside subdir
        if save_session:
            session_path = subdir / f"{skill.name}.session.yaml"

        result = execute_skill_prompt(
            skill=skill,
            workdir=subdir,
            params=effective_params,
            provider=provider_name,
            model=model,
            save_session=session_path,
            auto_learn=auto_learn,
            compact=compact,
            shared_context=shared_context,
            global_goal=global_goal,
            inject=inject,
        )
        session_output = (result.stdout or "") + (result.stderr or "")
        exit_code = result.exit_code
        internal_steps = result.internal_steps

    # script/run: skills produce no session file
    if session_path and not session_path.exists():
        session_path = None

    logger.info(
        "skill_executed",
        skill=skill.name,
        exit_code=exit_code,
        mode="script" if skill.has_scripts else ("run" if skill.run else "prompt"),
    )
    return exit_code, session_output, session_path, internal_steps


# ---------------------------------------------------------------------------
# Task executor — free-form CLI tools via TaskLoop
# ---------------------------------------------------------------------------


def _run_task(
    description: str,
    subdir: Path,
    provider_name: str,
    model: str | None,
    prev_context: str,
    agent_cfg: dict,
    save_session: bool = False,
) -> tuple[int, str, Path | None, int]:
    """Execute a free-form task in-process. Returns (exit_code, output, session_path, internal_steps)."""
    full_description = description
    if prev_context:
        full_description = (
            f"{description}\n\n---\n## Context from previous steps\n{prev_context}"
        )

    fastmarket_tools = agent_cfg.get("fastmarket_tools", {})
    system_commands = agent_cfg.get("system_commands", [])
    allowed = list(fastmarket_tools.keys()) + system_commands
    command_docs = agent_cfg.get("command_docs")
    agent_prompt = agent_cfg.get("agent_prompt")

    task_config = TaskConfig(
        fastmarket_tools=fastmarket_tools,
        system_commands=system_commands,
        allowed_commands=allowed,
        max_iterations=agent_cfg.get("max_iterations", 20),
        default_timeout=agent_cfg.get("default_timeout", 60),
        llm_timeout=0,
        temperature=agent_cfg.get("default_temperature", 0.3),
        command_docs=command_docs,
        agent_prompt=agent_prompt,
    )

    loop = TaskLoop(
        config=task_config,
        workdir=subdir,
        provider=provider_name,
        model=model,
        silent=True,
    )

    execute_fn = partial(
        resolve_and_execute_command,
        workdir=subdir,
        allowed=set(allowed),
        timeout=task_config.default_timeout,
    )

    loop.run(full_description, execute_fn, task_params={})

    end_reason = getattr(loop.session, "end_reason", "") or ""
    exit_code = 0 if "success" in end_reason else 1

    # Count internal steps (turns in the session)
    internal_steps = len(loop.session.turns) if loop.session else 0

    # Collect output from session turns
    session_output = _session_to_text(loop.session)

    session_path = None
    if save_session and loop.session:
        session_path = subdir / "task.session.yaml"
        loop.session.save(session_path)
        logger.info("task_session_saved", path=str(session_path))

    return exit_code, session_output, session_path, internal_steps


def _session_to_text(session) -> str:
    """Convert a Session object to readable text for summarisation."""
    if session is None:
        return "(no session)"
    parts = []
    for turn in session.turns:
        if turn.role == "assistant" and turn.content:
            parts.append(f"ASSISTANT: {turn.content[:500]}")
        for tc in turn.tool_calls:
            cmd = tc.arguments.get("command", "") if tc.arguments else ""
            stdout = (tc.stdout or "")[:300]
            stderr = (tc.stderr or "")[:200]
            exit_code = tc.exit_code if tc.exit_code is not None else "?"
            parts.append(f"CMD [{exit_code}]: {cmd}")
            if stdout:
                parts.append(f"  OUT: {stdout}")
            if stderr and exit_code != 0:
                parts.append(f"  ERR: {stderr}")
    return "\n".join(parts)[:4000]


def _save_router_session(
    goal: str,
    session_files: list[Path],
    run_root: Path,
    provider_name: str,
    model: str | None,
    max_iterations: int,
    state: RouterState,
) -> None:
    """Aggregate all skill session files into a single router.session.yaml."""
    import yaml
    from common.agent.session import Session

    all_turns = []
    for session_file in session_files:
        try:
            data = yaml.safe_load(session_file.read_text())
            if data and "turns" in data:
                s = Session.from_dict(data)
                all_turns.extend(s.turns)
                logger.info(
                    "aggregated_session", file=str(session_file), turns=len(s.turns)
                )
        except Exception as exc:
            logger.warning(
                "aggregate_session_failed", path=str(session_file), error=str(exc)
            )

    if state.done:
        end_reason = "completed"
    elif state.failed:
        end_reason = f"failed: {state.failure_reason}"
    else:
        end_reason = "max iterations reached"

    global_session = Session(
        task_description=goal,
        workdir=str(run_root),
        provider=provider_name,
        model=model or "default",
        max_iterations=max_iterations,
        turns=all_turns,
        end_time=dt.utcnow(),
        end_reason=end_reason,
        exit_code=0 if state.done else 1,
    )
    path = run_root / "router.session.yaml"
    global_session.save(path)
    logger.info("router_session_saved", path=str(path), turns=len(all_turns))


# ---------------------------------------------------------------------------
# YAML Export/Import functions
# ---------------------------------------------------------------------------


def _plan_to_yaml(plan: SkillPlan) -> str:
    """Convert a SkillPlan to user-readable YAML string."""
    import yaml

    data = {
        "goal": plan.goal,
        "success_criteria": plan.success_criteria,
        "preparation_plan": plan.preparation_plan,
        "plan": [],
    }

    for step in plan.steps:
        step_dict = {
            "step": step.step,
            "action": step.action,
        }

        if step.action == "run":
            step_dict["skill"] = step.skill_name
            if step.params:
                step_dict["params"] = step.params
            if step.inject:
                step_dict["inject"] = step.inject
            if step.context_hint:
                step_dict["context_hint"] = step.context_hint

        elif step.action == "task":
            step_dict["description"] = step.description
            if step.instructions:
                step_dict["instructions"] = step.instructions
            if step.context_hint:
                step_dict["context_hint"] = step.context_hint

        elif step.action == "ask":
            step_dict["question"] = step.question

        data["plan"].append(step_dict)

    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _execution_log_to_yaml(state: RouterState) -> str:
    """Convert RouterState to a user-readable execution log YAML."""
    import yaml

    if state.done:
        status = "completed"
    elif state.failed:
        status = "failed"
    else:
        status = "max_iterations"

    data = {
        "goal": state.goal,
        "status": status,
        "final_result": state.final_result if state.done else state.failure_reason,
        "preparation": state.preparation,
        "success_criteria": state.success_criteria,
        "total_steps": len(state.attempts),
        "execution": [],
    }

    for attempt in state.attempts:
        attempt_dict = {
            "step": attempt.iteration,
            "action": attempt.action,
            "skill": attempt.skill_name,
            "params": attempt.params,
            "success": attempt.success,
            "exit_code": attempt.exit_code,
            "summary": attempt.runner_summary,
        }

        if attempt.raw_output:
            # Truncate for readability
            output = attempt.raw_output.strip()
            if len(output) > 500:
                output = output[:500] + "... [truncated]"
            attempt_dict["output_preview"] = output

        data["execution"].append(attempt_dict)

    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _export_plan_to_file(plan: SkillPlan, filepath: str) -> None:
    """Export plan to YAML file or stdout."""
    import sys

    yaml_content = _plan_to_yaml(plan)

    if filepath == "-":
        # Export to stdout
        print(yaml_content)
    else:
        # Export to file
        path = Path(filepath)
        path.write_text(yaml_content)
        logger.info("plan_exported", path=str(path))


def _export_execution_log(state: RouterState, filepath: str) -> None:
    """Export execution log to YAML file or stdout."""
    import sys

    yaml_content = _execution_log_to_yaml(state)

    if filepath == "-":
        # Export to stdout
        print(yaml_content)
    else:
        # Export to file
        path = Path(filepath)
        path.write_text(yaml_content)
        logger.info("execution_log_exported", path=str(path))


def _export_successful_plan(state: RouterState, filepath: str) -> None:
    """Export only the successful steps as a clean plan YAML."""
    import yaml

    successful_steps = []
    step_num = 0

    for attempt in state.attempts:
        if attempt.success or attempt.action == "ask":
            step_num += 1
            step_dict = {
                "step": step_num,
                "action": attempt.action,
            }

            if attempt.action == "run":
                step_dict["skill"] = attempt.skill_name
                if attempt.params:
                    step_dict["params"] = attempt.params
            elif attempt.action == "task":
                # Extract description from runner_summary or raw_output
                desc = attempt.runner_summary or f"Task: {attempt.skill_name}"
                step_dict["description"] = desc
            elif attempt.action == "ask":
                step_dict["question"] = attempt.params.get("question", "")

            successful_steps.append(step_dict)

    if not successful_steps:
        return

    data = {
        "goal": state.goal,
        "success_criteria": state.success_criteria,
        "final_result": state.final_result if state.done else state.failure_reason,
        "plan": successful_steps,
    }

    yaml_content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if filepath == "-":
        print(yaml_content)
    else:
        path = Path(filepath)
        path.write_text(yaml_content)
        logger.info("successful_plan_exported", path=str(path))


def _substitute_placeholders(obj: Any, params: dict[str, str]) -> Any:
    """Recursively replace {{key}} and {{key:default}} placeholders in string values.
    
    Supports two forms:
    - {{key}} — mandatory, errors if not in params
    - {{key:default}} — optional, uses 'default' if key not in params
    """
    import re

    if isinstance(obj, str):
        def _replace(m):
            inner = m.group(1)  # e.g. "key" or "key:default"
            if ":" in inner:
                key, default = inner.split(":", 1)
                return params.get(key.strip(), default) if params else default
            else:
                return params.get(inner, m.group(0)) if params else m.group(0)
        return re.sub(r"\{\{([^}]+)\}\}", _replace, obj)
    if isinstance(obj, dict):
        return {k: _substitute_placeholders(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_placeholders(item, params) for item in obj]
    return obj


def _find_missing_placeholders(obj: Any, path: str = "") -> list[str]:
    """Find remaining unsubstituted mandatory {{key}} placeholders.
    
    Only reports {{key}} without defaults as missing.
    {{key:default}} that resolved to the default are NOT missing.
    """
    import re

    missing = []
    if isinstance(obj, str):
        # Find all remaining {{...}} patterns
        for m in re.finditer(r"\{\{([^}]+)\}\}", obj):
            inner = m.group(1)
            if ":" not in inner:
                missing.append(inner.strip())
    elif isinstance(obj, dict):
        for k, v in obj.items():
            missing.extend(_find_missing_placeholders(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            missing.extend(_find_missing_placeholders(item, f"{path}[{i}]"))
    return missing


def _import_plan_from_yaml(filepath: str, workdir: str = ".", params: dict[str, str] | None = None) -> SkillPlan:
    """Import a skill plan from YAML file, substituting {{key}} placeholders with params."""
    import yaml

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {filepath}")

    # Read raw data BEFORE substitution
    raw_data = yaml.safe_load(path.read_text())
    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid plan YAML format in {filepath}")

    # Apply placeholder substitution (including defaults for {{key:default}} patterns)
    data = _substitute_placeholders(dict(raw_data), params)

    # Check for remaining unsubstituted mandatory placeholders
    missing = _find_missing_placeholders(data)
    if missing:
        raise ValueError(
            f"Unresolved mandatory placeholders in plan: {', '.join(set(missing))}. "
            f"Provide values with -p/--param options."
        )

    goal = data.get("goal", "")
    if not goal:
        raise ValueError(f"Plan missing 'goal' field in {filepath}")

    plan_steps = []
    plan_data = data.get("plan", [])
    raw_plan_data = raw_data.get("plan", [])

    for i, step_dict in enumerate(plan_data, 1):
        action = step_dict.get("action", "")
        if action not in ("run", "task", "ask"):
            raise ValueError(f"Step {i} has invalid action: {action}")

        # Get original (pre-substitution) values
        raw_step = raw_plan_data[i - 1] if i - 1 < len(raw_plan_data) else {}
        original_desc = raw_step.get("description", "")
        original_params = raw_step.get("params", {}) or {}

        step = SkillPlanStep(
            step=i,
            action=action,
            skill_name=step_dict.get("skill", ""),
            params=step_dict.get("params", {}),
            original_params=original_params,
            inject=step_dict.get("inject", ""),
            description=step_dict.get("description", ""),
            original_description=original_desc,
            instructions=step_dict.get("instructions", ""),
            question=step_dict.get("question", ""),
            context_hint=step_dict.get("context_hint", ""),
            name=step_dict.get("name", ""),
        )
        plan_steps.append(step)

    return SkillPlan(
        goal=goal,
        steps=plan_steps,
        success_criteria=data.get("success_criteria", ""),
        preparation_plan=data.get("preparation_plan", ""),
    )


# ---------------------------------------------------------------------------
# Run statistics
# ---------------------------------------------------------------------------


@dataclass
class RunStatistics:
    """Statistics about a completed router run."""
    total_duration_seconds: float
    total_steps: int  # router steps + all internal steps
    router_steps: int  # top-level router iterations
    internal_steps: int  # TaskLoop turns within tasks and prompt skills
    successful_steps: int
    failed_steps: int
    skipped_steps: int
    run_actions: int
    task_actions: int
    ask_actions: int
    unique_skills_executed: int


def calculate_run_statistics(state: RouterState) -> RunStatistics:
    """Calculate statistics from a completed router run."""
    router_steps = len(state.attempts)
    internal_steps = sum(a.internal_steps for a in state.attempts)
    total_steps = router_steps + internal_steps
    
    successful_steps = sum(1 for a in state.attempts if a.success)
    failed_steps = sum(1 for a in state.attempts if not a.success and a.exit_code != 0)
    skipped_steps = sum(1 for a in state.attempts if a.exit_code == 0 and not a.success and "skipped" in a.runner_summary.lower())
    
    run_actions = sum(1 for a in state.attempts if a.action == "run")
    task_actions = sum(1 for a in state.attempts if a.action == "task")
    ask_actions = sum(1 for a in state.attempts if a.action == "ask")
    
    unique_skills = set()
    for a in state.attempts:
        if a.action == "run":
            unique_skills.add(a.skill_name)
    
    total_duration = state.end_time - state.start_time if state.end_time > 0 else 0.0
    
    return RunStatistics(
        total_duration_seconds=total_duration,
        total_steps=total_steps,
        router_steps=router_steps,
        internal_steps=internal_steps,
        successful_steps=successful_steps,
        failed_steps=failed_steps,
        skipped_steps=skipped_steps,
        run_actions=run_actions,
        task_actions=task_actions,
        ask_actions=ask_actions,
        unique_skills_executed=len(unique_skills),
    )


def format_statistics(stats: RunStatistics) -> str:
    """Format statistics as a human-readable string."""
    minutes = int(stats.total_duration_seconds // 60)
    seconds = stats.total_duration_seconds % 60
    
    if minutes > 0:
        time_str = f"{minutes}m {seconds:.1f}s"
    else:
        time_str = f"{seconds:.1f}s"
    
    lines = [
        "=" * 60,
        "RUN STATISTICS",
        "=" * 60,
        f"Total run time:          {time_str}",
        f"Total steps executed:    {stats.total_steps}",
        f"  Router steps:          {stats.router_steps}",
        f"  Internal steps:        {stats.internal_steps}",
        "-" * 60,
        f"Results:",
        f"  Successful:            {stats.successful_steps}",
        f"  Failed:                {stats.failed_steps}",
        f"  Skipped:               {stats.skipped_steps}",
        "-" * 60,
        f"Actions breakdown:",
        f"  Skill executions:      {stats.run_actions}",
        f"  Task executions:       {stats.task_actions}",
        f"  User questions:        {stats.ask_actions}",
        "-" * 60,
        f"Unique skills used:      {stats.unique_skills_executed}",
        "=" * 60,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main router loop
# ---------------------------------------------------------------------------


def run_router(
    goal: str,
    provider,
    model: str | None = None,
    workdir: str = ".",
    max_iterations: int = 10,
    skill_timeout: int = 300,
    retry_limit: int = 2,
    verbose: bool = False,
    auto_learn: bool = False,
    compact: bool = False,
    interaction: InteractionPlugin | None = None,
    evaluation_prompt: str | None = None,
    skip_evaluation: bool = False,
    save_session: bool = False,
    skills_dir: Path | None = None,
    isolation_mode: str = "skill",
    shared_context: Any = None,
    export_plan_path: str | None = None,
    import_plan_path: str | None = None,
    import_params: dict[str, str] | None = None,
    interactive: bool = False,
    export_successful_path: str | None = None,
) -> RouterState:
    """Orchestrate skills and tasks to achieve a goal.

    isolation_mode:
    - "none": skills use workdir directly (cooperation enabled)
    - "run": create one isolated dir for the entire run
    - "skill": create run dir + subdirectory per skill (default, backward compatible)

    shared_context:
    - SharedContext instance that skills can read/write to cooperate
    """
    import importlib.util

    # Load skill agent config via importlib to avoid sys.path ordering issues
    skill_cli_setup_path = (
        Path(__file__).parent.parent / "commands" / "setup" / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location(
        "skill_cli_setup", skill_cli_setup_path
    )
    skill_cli_setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill_cli_setup)
    init_skill_agent_config = skill_cli_setup.init_skill_agent_config

    from common.core.config import load_tool_config
    from common.llm.registry import get_default_provider_name

    if interaction is None:
        interaction = CLIInteractionPlugin()

    try:
        config = load_tool_config("apply")
        provider_name = get_default_provider_name(config)
    except Exception:
        provider_name = getattr(provider, "name", "default")

    agent_cfg = init_skill_agent_config()
    skills = discover_skills(skills_dir or get_skills_dir())

    workdir_path = Path(workdir).expanduser().resolve()

    # Create run_root based on isolation mode
    if isolation_mode == "none":
        run_root = None  # Will use workdir_path directly
    else:
        run_root = make_run_root(workdir_path)

    state = RouterState(
        goal=goal,
        attempts=[],
        iteration=0,
        max_iterations=max_iterations,
        run_root=run_root,
        isolation_mode=isolation_mode,
        shared_context=shared_context,
        start_time=time.time(),
    )

    # Handle export paths - files go into run_root (or workdir if no isolation)
    export_target = run_root if run_root is not None else workdir_path
    plan_export_path = None
    execution_export_path = None
    
    if export_plan_path:
        if export_plan_path == "-":
            # Special case: export to stdout
            plan_export_path = "-"
            execution_export_path = "-"
        else:
            # If export_plan_path is just a filename or relative path, use export_target
            export_path = Path(export_plan_path)
            if export_path.is_absolute():
                # If absolute path provided, use it as-is
                plan_export_path = export_path
                execution_export_path = export_path.parent / f"{export_path.stem}.execution{export_path.suffix}"
            else:
                # Relative path or filename - place in export_target
                plan_export_path = export_target / export_path
                execution_export_path = export_target / f"{export_path.stem}.execution{export_path.suffix}"

    # Import plan if provided
    if import_plan_path:
        try:
            state.imported_plan = _import_plan_from_yaml(import_plan_path, workdir, params=import_params)
            logger.info("plan_imported", path=import_plan_path, steps=len(state.imported_plan.steps))
            if verbose:
                print(f"\n[router] Imported plan from: {import_plan_path}")
                if import_params:
                    print(f"[router] Substituted params: {', '.join(import_params.keys())}")
                print(f"[router] Plan has {len(state.imported_plan.steps)} steps")
        except Exception as exc:
            state.failed = True
            state.failure_reason = f"Failed to import plan: {exc}"
            state.end_time = time.time()
            return state

    if not skills:
        state.failed = True
        state.failure_reason = "No skills available"
        state.end_time = time.time()
        return state

    # Load prompt overrides
    from cli.main import get_skill_prompt_manager

    prompt_manager = get_skill_prompt_manager()
    plan_prompt = prompt_manager.get("plan") if prompt_manager else None
    preparation_prompt_cfg = (
        prompt_manager.get("preparation") if prompt_manager else None
    )

    if skip_evaluation:
        evaluation_prompt_cfg = None
    elif evaluation_prompt is not None:
        evaluation_prompt_cfg = evaluation_prompt
    else:
        evaluation_prompt_cfg = (
            prompt_manager.get("evaluation") if prompt_manager else None
        )

    # --- Preparation ---
    try:
        preparation = _call_preparation(
            goal, provider, model, skills, prompt_template=preparation_prompt_cfg
        )
        state.success_criteria = preparation.success_criteria
        state.preparation = preparation.plan
        logger.info("preparation_done", criteria=preparation.success_criteria)
        if verbose:
            print(f"\n[router] Preparation plan:\n{preparation.plan}")
            print(f"[router] Success criteria: {preparation.success_criteria}")
    except Exception as exc:
        state.failed = True
        state.failure_reason = f"Preparation failed: {exc}"
        state.end_time = time.time()
        return state

    session_files: list[Path] = []
    prev_context = ""
    planned_steps: list[SkillPlanStep] = []

    # --- Planning loop ---
    while state.iteration < max_iterations and not state.done and not state.failed:
        state.iteration += 1

        if verbose:
            history_preview = _format_history(state.attempts)
            print(f"\n[router] History sent to planner ({len(history_preview)} chars):")
            print(history_preview[:500] + ("..." if len(history_preview) > 500 else ""))

        # Use imported plan if available, otherwise call planner
        if state.imported_plan:
            # Use imported plan step
            step_index = len(state.attempts)
            if step_index < len(state.imported_plan.steps):
                plan_step = state.imported_plan.steps[step_index]
                plan = {
                    "action": plan_step.action,
                    "skill_name": plan_step.skill_name,
                    "params": plan_step.params,
                    "context_hint": plan_step.context_hint,
                    "description": plan_step.description,
                    "original_description": plan_step.original_description,
                    "question": plan_step.question,
                    "name": plan_step.name,
                    "reason": f"From imported plan (step {plan_step.step})",
                }
                if verbose:
                    print(f"\n[router] Using imported plan step {plan_step.step}: {plan_step.action}")
            else:
                # Plan exhausted, mark as done
                plan = {"action": "done", "reason": "Imported plan exhausted"}
        else:
            # Call the planner
            try:
                plan = _call_plan(
                    state, provider, model, skills, prompt_template=plan_prompt
                )
            except Exception as exc:
                state.failed = True
                state.failure_reason = f"Planner failed: {exc}"
                break

        action = plan.get("action", "").strip()
        logger.debug("router_plan", iteration=state.iteration, action=action)
        if verbose:
            print(f"\n[router] Iteration {state.iteration}: planner chose action='{action}'")
            if action == "run":
                print(f"  skill_name: {plan.get('skill_name')}")
                print(f"  params: {plan.get('params')}")
                print(f"  reason: {plan.get('reason')}")
            elif action == "task":
                print(f"  description: {plan.get('description')}")
            elif action in ("done", "fail"):
                print(f"  reason: {plan.get('reason')}")

        # Track planned step for export
        if action not in ("done", "fail"):
            planned_step = SkillPlanStep(
                step=state.iteration,
                action=action,
                skill_name=plan.get("skill_name", ""),
                params={str(k): str(v) for k, v in (plan.get("params") or {}).items()},
                inject=plan.get("inject", ""),
                description=plan.get("description", ""),
                instructions=plan.get("instructions", ""),
                question=plan.get("question", ""),
                context_hint=plan.get("context_hint", ""),
            )
            planned_steps.append(planned_step)

        # Terminal actions
        if action == "done":
            state.done = True
            state.final_result = str(plan.get("reason", "Goal achieved"))
            break

        if action == "fail":
            state.failed = True
            state.failure_reason = str(plan.get("reason", "Router declared failure"))
            break

        # Interactive approval hook
        if interactive and action in ("run", "task"):
            approval = InteractiveApprovalPlugin().approve(plan, state.attempts)

            if approval.action == "quit":
                state.done = True
                state.final_result = "User quit during interactive mode"
                break

            if approval.action == "skip":
                click.echo(f"[interactive] Step skipped by user", err=True)
                attempt = SkillAttempt(
                    action=action,
                    skill_name=plan.get("skill_name", "(task)") if action == "run" else "(task)",
                    params={str(k): str(v) for k, v in (plan.get("params") or {}).items()},
                    exit_code=0,
                    runner_summary="Skipped by user in interactive mode",
                    context="",
                    context_hint=plan.get("context_hint", ""),
                    success=True,
                    iteration=state.iteration,
                    subdir=Path(""),
                    raw_output="",
                    internal_steps=0,
                )
                state.attempts.append(attempt)
                continue

            if approval.action == "replan":
                click.echo(f"[interactive] Asking planner for an alternative...", err=True)
                # Call planner again with rejection feedback
                try:
                    plan = _call_plan(
                        state, provider, model, skills,
                        prompt_template=plan_prompt,
                        extra_context="User rejected the previous proposed step. Please propose a different approach.",
                    )
                    action = plan.get("action", "").strip()
                    # Re-track the new planned step
                    if action not in ("done", "fail"):
                        planned_step = SkillPlanStep(
                            step=state.iteration,
                            action=action,
                            skill_name=plan.get("skill_name", ""),
                            params={str(k): str(v) for k, v in (plan.get("params") or {}).items()},
                            inject=plan.get("inject", ""),
                            description=plan.get("description", ""),
                            instructions=plan.get("instructions", ""),
                            question=plan.get("question", ""),
                            context_hint=plan.get("context_hint", ""),
                        )
                        planned_steps.append(planned_step)
                    # Handle terminal actions again
                    if action == "done":
                        state.done = True
                        state.final_result = str(plan.get("reason", "Goal achieved"))
                        break
                    if action == "fail":
                        state.failed = True
                        state.failure_reason = str(plan.get("reason", "Router declared failure"))
                        break
                    if action == "ask":
                        question = str(plan.get("question", "What should I do next?"))
                        answer = interaction.ask(question)
                        attempt = SkillAttempt(
                            action="ask",
                            skill_name="(user)",
                            params={"question": question},
                            exit_code=0,
                            runner_summary=f"User answered: {answer}",
                            context=f"User was asked: {question}\nUser answered: {answer}",
                            context_hint="",
                            success=True,
                            iteration=state.iteration,
                            subdir=Path(""),
                            raw_output="",
                            internal_steps=0,
                        )
                        state.attempts.append(attempt)
                        prev_context = attempt.context
                        if verbose:
                            _print_attempt(attempt)
                        continue
                    # Fall through to execute the new plan
                    click.echo(f"[interactive] New plan: {action}", err=True)
                except Exception as exc:
                    click.echo(f"[interactive] Replan failed: {exc}. Proceeding with original.", err=True)

            if approval.action == "edit" and approval.modified_plan:
                plan = approval.modified_plan
                action = plan.get("action", "").strip()
                click.echo(f"[interactive] Step modified by user", err=True)

            if approval.action == "accept":
                if approval.modified_plan:
                    plan = approval.modified_plan
                click.echo(f"[interactive] Step accepted", err=True)

        # Ask user
        if action == "ask":
            question = str(plan.get("question", "What should I do next?"))
            answer = interaction.ask(question)
            attempt = SkillAttempt(
                action="ask",
                skill_name="(user)",
                params={"question": question},
                exit_code=0,
                runner_summary=f"User answered: {answer}",
                context=f"User was asked: {question}\nUser answered: {answer}",
                context_hint="",
                success=True,
                iteration=state.iteration,
                subdir=Path(""),
                raw_output="",
                internal_steps=0,
            )
            state.attempts.append(attempt)
            prev_context = attempt.context
            if verbose:
                _print_attempt(attempt)
            continue

        # Run skill
        if action == "run":
            skill_name = str(plan.get("skill_name", "")).strip()
            params = {str(k): str(v) for k, v in (plan.get("params") or {}).items()}
            context_hint = str(plan.get("context_hint", ""))
            inject_instructions = plan.get("inject")
            skill_internal_steps = 0

            # Auto-chain: detect when previous skill output should be passed as a param
            if state.attempts and context_hint:
                import re as re_module

                # Look for patterns like "output of X as param_name" or "X's output as param"
                prev_attempt = state.attempts[-1]
                prev_skill_name = prev_attempt.skill_name

                # Check if context_hint mentions passing output to a param
                match = re_module.search(
                    rf"(?:output|result) of\s+({prev_skill_name}[-\w]*)\s+as\s+(\w+)",
                    context_hint,
                    re_module.IGNORECASE,
                )
                if match and prev_attempt.raw_output:
                    # Extract stdout from raw output (first line usually)
                    output_value = prev_attempt.raw_output.strip().split("\n")[0]
                    target_param = match.group(2)
                    params[target_param] = output_value
                    logger.info(
                        "auto_chain_param",
                        from_skill=prev_skill_name,
                        to_skill=skill_name,
                        param=target_param,
                        value=output_value[:100],
                    )

            matched = next((s for s in skills if s.name == skill_name), None)
            if not matched:
                state.failed = True
                state.failure_reason = f"Planner returned unknown skill: {skill_name!r}"
                break

            # Prevent repeating a successful skill with the same params
            prev_success_match = any(
                a.skill_name == skill_name
                and a.action == "run"
                and a.success
                and a.params == params
                for a in state.attempts
            )
            if prev_success_match:
                attempt = SkillAttempt(
                    action="run",
                    skill_name=skill_name,
                    params=params,
                    exit_code=1,
                    runner_summary=f"Skipped: {skill_name} with these params already succeeded — planner should choose next skill",
                    context="",
                    context_hint=context_hint,
                    success=False,
                    iteration=state.iteration,
                    subdir=Path(""),
                    raw_output="",
                    internal_steps=0,
                )
                state.attempts.append(attempt)
                if verbose:
                    _print_attempt(attempt)
                continue

            failed_count = sum(
                1
                for a in state.attempts
                if a.skill_name == skill_name and a.action == "run" and not a.success
            )
            if failed_count >= retry_limit:
                attempt = SkillAttempt(
                    action="run",
                    skill_name=skill_name,
                    params=params,
                    exit_code=1,
                    runner_summary=f"Skipped: retry limit ({retry_limit}) reached for {skill_name}",
                    context="",
                    context_hint=context_hint,
                    success=False,
                    iteration=state.iteration,
                    subdir=Path(""),
                    raw_output="",
                    internal_steps=0,
                )
                state.attempts.append(attempt)
                if verbose:
                    _print_attempt(attempt)
                continue

            # Determine workdir based on isolation mode
            if isolation_mode == "none":
                workdir_for_skill = workdir_path
                subdir_for_record = Path("")
            else:
                subdir_for_record = _make_subdir(run_root, state.iteration, skill_name, isolation_mode)
                workdir_for_skill = subdir_for_record

            exit_code, session_output, session_path, skill_internal_steps = _run_skill(
                skill=matched,
                params=params,
                subdir=workdir_for_skill,
                provider_name=provider_name,
                model=model,
                auto_learn=auto_learn,
                compact=compact,
                prev_context=prev_context,
                save_session=save_session,
                shared_context=state.shared_context,
                global_goal=state.goal,
                inject=inject_instructions,
            )
            label = skill_name

        # Free-form task
        elif action == "task":
            description = str(plan.get("description", "")).strip()
            context_hint = str(plan.get("context_hint", ""))
            params = {str(k): str(v) for k, v in (plan.get("params") or {}).items()}
            task_internal_steps = 0

            if not description:
                state.failed = True
                state.failure_reason = (
                    "Planner issued 'task' action with no description"
                )
                break

            if isolation_mode == "none":
                workdir_for_task = workdir_path
                subdir_for_record = Path("")
            else:
                subdir_for_record = _make_subdir(run_root, state.iteration, "task", isolation_mode)
                workdir_for_task = subdir_for_record

            exit_code, session_output, session_path, task_internal_steps = _run_task(
                description=description,
                subdir=workdir_for_task,
                provider_name=provider_name,
                model=model,
                prev_context=prev_context,
                agent_cfg=agent_cfg,
                save_session=save_session,
            )
            label = f"(task) {description[:60]}"

        else:
            state.failed = True
            state.failure_reason = f"Invalid planner action: {action!r}"
            break

        if session_path:
            session_files.append(session_path)

        try:
            runner_summary = _call_runner_summary(
                label, params, session_output, provider, model
            )
        except Exception as exc:
            runner_summary = f"Summary failed: {exc}"

        try:
            new_context = _call_context_extract(
                goal=state.goal,
                label=label,
                params=params,
                session_output=session_output,
                next_step_hint=context_hint,
                provider=provider,
                model=model,
            )
        except Exception as exc:
            new_context = f"Context extraction failed: {exc}"

        # Evaluation
        if evaluation_prompt_cfg is not None:
            try:
                evaluation = _call_evaluation(
                    state=state,
                    last_summary=runner_summary,
                    success_criteria=state.success_criteria,
                    provider=provider,
                    model=model,
                    prompt_template=evaluation_prompt_cfg,
                )
                logger.info(
                    "evaluation",
                    satisfied=evaluation.satisfied,
                    reason=evaluation.reason,
                )
                if evaluation.satisfied:
                    state.done = True
                    state.final_result = evaluation.reason
            except Exception as exc:
                logger.warning("evaluation_failed", error=str(exc))

        prev_context = new_context

        # Determine internal steps based on action type
        internal_steps = 0
        if action == "run":
            internal_steps = skill_internal_steps
        elif action == "task":
            internal_steps = task_internal_steps

        attempt = SkillAttempt(
            action=action,
            skill_name=skill_name if action == "run" else label,
            params=params,
            exit_code=exit_code,
            runner_summary=runner_summary,
            context=new_context,
            context_hint=context_hint,
            success=(exit_code == 0),
            iteration=state.iteration,
            subdir=subdir_for_record,
            raw_output=session_output,
            internal_steps=internal_steps,
        )
        state.attempts.append(attempt)

        if verbose:
            _print_attempt(attempt)

        if state.done:
            break

        if len(state.attempts) >= 2:
            last = state.attempts[-1]
            prev = state.attempts[-2]
            if (
                last.action == prev.action
                and last.skill_name == prev.skill_name
                and last.params == prev.params
                and last.success
                and prev.success
            ):
                state.done = True
                state.final_result = (
                    f"Goal appears achieved — same {last.action} "
                    f"{last.skill_name} succeeded twice with no progress"
                )
                break

        if state.iteration >= max_iterations - 1:
            run_attempts = [a for a in state.attempts if a.action == "run"]
            task_attempts = [a for a in state.attempts if a.action == "task"]
            if run_attempts and task_attempts:
                state.done = True
                state.final_result = (
                    "Max iterations near — at least one skill and task ran successfully"
                )
                break

    if not state.done and not state.failed and state.iteration >= max_iterations:
        state.failed = True
        state.failure_reason = (
            f"Max iterations ({max_iterations}) reached without completion"
        )

    # Export plan if requested (after execution is complete)
    if plan_export_path and planned_steps:
        try:
            final_plan = SkillPlan(
                goal=goal,
                steps=planned_steps,
                success_criteria=state.success_criteria,
                preparation_plan=state.preparation,
            )
            _export_plan_to_file(final_plan, str(plan_export_path))
            if verbose:
                print(f"\n[router] Plan exported to: {plan_export_path}")
        except Exception as exc:
            logger.warning("plan_export_failed", error=str(exc))
            if verbose:
                print(f"\n[router] Warning: Failed to export plan: {exc}")

    # Export execution log if requested
    if execution_export_path:
        try:
            _export_execution_log(state, str(execution_export_path))
            if verbose:
                print(f"\n[router] Execution log exported to: {execution_export_path}")
        except Exception as exc:
            logger.warning("execution_export_failed", error=str(exc))
            if verbose:
                print(f"\n[router] Warning: Failed to export execution log: {exc}")

    # Export successful plan if requested (especially useful in interactive mode)
    if export_successful_path:
        try:
            _export_successful_plan(state, str(export_successful_path))
            if verbose:
                print(f"\n[router] Successful plan exported to: {export_successful_path}")
        except Exception as exc:
            logger.warning("successful_plan_export_failed", error=str(exc))
            if verbose:
                print(f"\n[router] Warning: Failed to export successful plan: {exc}")

    if save_session and session_files:
        # When isolation_mode is "none", use workdir_path as the session save location
        session_root = run_root if run_root is not None else workdir_path
        _save_router_session(
            goal=goal,
            session_files=session_files,
            run_root=session_root,
            provider_name=provider_name,
            model=model,
            max_iterations=max_iterations,
            state=state,
        )

    state.end_time = time.time()
    return state
