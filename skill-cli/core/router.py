from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from common import structlog
from common.agent.loop import TaskConfig, TaskLoop
from common.agent.executor import resolve_and_execute_command
from common.core.paths import get_skills_dir
from common.llm.base import LLMRequest
from core.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLAN_PROMPT = """You are a skill orchestrator. Your job is to achieve a goal by
selecting and sequencing skills, one at a time.

## Goal
{goal}

## Available Skills
{skills_list}

## History
{history}

## Instructions

Decide what to do next. You must return ONLY a JSON object.

### Actions

Run a specific skill:
{{
  "action": "run",
  "skill_name": "the-skill-name",
  "params": {{"key": "value"}},
  "reason": "one sentence why",
  "context_hint": "what the next skill will need from this result"
}}

Run a free-form task with raw CLI tools (use when no skill fits or a skill failed and you need to improvise):
{{
  "action": "task",
  "description": "detailed description of what to accomplish",
  "reason": "one sentence why no skill fits or why improvising is better",
  "context_hint": "what the next step will need from this result"
}}

Ask the user a question when you have genuine ambiguity you cannot resolve yourself:
{{
  "action": "ask",
  "question": "clear, specific question for the user",
  "reason": "one sentence why you need this information"
}}

Goal fully achieved:
{{
  "action": "done",
  "reason": "one sentence summary of what was accomplished"
}}

Goal cannot be achieved (repeated failures, missing capability):
{{
  "action": "fail",
  "reason": "one sentence explanation of why"
}}

### Rules
- Only use skills from the Available Skills list for "run" actions
- Use "task" when no skill fits OR when a skill failed and you want to try a different approach with raw tools
- Use "ask" sparingly — only when the goal is genuinely ambiguous, not just when a skill fails
- If a previous attempt failed, try a different approach (different skill, different params, or "task")
- Never repeat the exact same skill+params that already failed
- Params must be concrete values, not placeholders
- If a skill produced output that a next skill needs, it is available in history as context
"""

RUNNER_SUMMARY_PROMPT = """Write a concise summary (max 15 lines) for the orchestrator:
- Did it succeed or fail?
- What approach was used?
- What errors occurred? What is the root cause?
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
    skill_name: str  # skill name or "(task)" or "(ask)"
    params: dict[str, str]
    exit_code: int
    runner_summary: str
    context: str
    context_hint: str
    success: bool
    iteration: int
    subdir: Path


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


# ---------------------------------------------------------------------------
# Interaction plugin interface
# ---------------------------------------------------------------------------

class InteractionPlugin:
    """Base class for user interaction during skill routing.

    Default implementation uses CLI stdin/stdout.
    Override to implement Telegram, web UI, etc.
    """

    def ask(self, question: str) -> str:
        """Ask the user a question and return their answer."""
        raise NotImplementedError


class CLIInteractionPlugin(InteractionPlugin):
    """Default: ask via terminal prompt."""

    def ask(self, question: str) -> str:
        print(f"\n[router] Question for you:\n  {question}")
        try:
            answer = input("Your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        return answer


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
        subdir_name = a.subdir.name if a.subdir and a.subdir.name else "N/A"
        label = a.skill_name
        lines.append(f"Step {a.iteration} [{a.action}]: {label}({params_str}) → {status}")
        lines.append(f"  Subdir: {subdir_name}")
        lines.append(f"  Summary: {a.runner_summary[:300]}")
        if a.context:
            lines.append(f"  Context available: yes ({len(a.context)} chars)")
    return "\n".join(lines)


def _make_subdir(workdir: Path, iteration: int, label: str) -> Path:
    name = f"{iteration:02d}_{label}"
    subdir = workdir / name
    subdir.mkdir(parents=True, exist_ok=True)
    logger.info("created_subdir", subdir=str(subdir), iteration=iteration)
    return subdir


def _call_plan(state: RouterState, provider, model: str | None, skills: list[Skill]) -> dict:
    prompt = PLAN_PROMPT.format(
        goal=state.goal,
        skills_list=build_skills_list(skills),
        history=_format_history(state.attempts),
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=600)
    response = provider.complete(req)
    raw = (response.content or "").strip()

    _debug = os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {"1", "true", "TRUE"}
    if _debug:
        print(f"[router][plan] raw response:\n{raw}")

    if not raw:
        raise ValueError(
            f"Planner returned empty response. "
            f"Model: {response.model}. Set SKILL_ROUTER_DEBUG_LLM=1 for details."
        )

    # Strip markdown fences if present
    cleaned = raw
    if "```" in cleaned:
        cleaned = cleaned.replace("```json", "```")
        parts = [p.strip() for p in cleaned.split("```") if p.strip()]
        candidates = [p for p in parts if p.startswith("{") and p.endswith("}")]
        if candidates:
            cleaned = candidates[0]
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)
    except Exception as exc:
        raise ValueError(f"Planner returned invalid JSON: {raw[:300]!r}. Error: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Planner returned non-object JSON")
    return data


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
    req = LLMRequest(prompt=prompt, model=model, temperature=0.3, max_tokens=500)
    response = provider.complete(req)
    summary = (response.content or "").strip()
    return summary or (session_output[:1000] if session_output else "(no summary)")


def _call_context_extract(
    goal: str,
    label: str,  # skill name or task description prefix
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
        next_step_hint=next_step_hint or "Extract any useful data or results for the next step.",
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.3, max_tokens=1000)
    response = provider.complete(req)
    return (response.content or "").strip()


def _session_to_text(session) -> str:
    """Convert a Session object to a readable text summary."""
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


def _print_attempt(attempt: SkillAttempt) -> None:
    status = "success" if attempt.success else "failed"
    params = ", ".join(f"{k}={v}" for k, v in attempt.params.items())
    subdir_name = attempt.subdir.name if attempt.subdir else "N/A"
    print(f"[router] step {attempt.iteration} [{attempt.action}]: {attempt.skill_name}({params}) -> {status}")
    print(f"[router] subdir: {subdir_name}")
    print(f"[router] summary: {attempt.runner_summary[:300]}")


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def _run_skill(
    skill: Skill,
    params: dict[str, str],
    subdir: Path,
    provider_name: str,
    model: str | None,
    skill_timeout: int,
    auto_learn: bool,
    compact: bool,
    prev_context: str,
) -> tuple[int, object]:  # (exit_code, session)
    """Execute a skill directly in-process. Returns (exit_code, session)."""
    from functools import partial
    from commands.setup import init_skill_agent_config

    # Inject router context as a param so the skill's LLM can see it
    effective_params = dict(params)
    if prev_context:
        effective_params["_router_context"] = prev_context

    body = skill.get_body()
    for key, value in effective_params.items():
        body = body.replace(f"{{{key}}}", str(value))

    learn_path = skill.path / "LEARN.md"
    if learn_path.exists():
        learn_content = learn_path.read_text(encoding="utf-8")
        body = f"{body}\n\n---\n## Lessons from previous runs\n{learn_content}"

    agent_cfg = init_skill_agent_config()
    fastmarket_tools = agent_cfg.get("fastmarket_tools", {})
    system_commands = agent_cfg.get("system_commands", [])
    allowed = list(fastmarket_tools.keys()) + system_commands

    task_config = TaskConfig(
        fastmarket_tools=fastmarket_tools,
        system_commands=system_commands,
        allowed_commands=allowed,
        max_iterations=skill.max_iterations or agent_cfg.get("max_iterations", 20),
        default_timeout=agent_cfg.get("default_timeout", 60),
        llm_timeout=skill.llm_timeout or 0,
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

    loop.run(body, execute_fn, task_params=effective_params)

    end_reason = getattr(loop.session, "end_reason", "") or ""
    exit_code = 0 if "success" in end_reason else 1

    if auto_learn and loop.session:
        _try_auto_learn(skill, effective_params, loop.session, subdir, None, model, compact)

    return exit_code, loop.session


def _run_task(
    description: str,
    subdir: Path,
    provider_name: str,
    model: str | None,
    prev_context: str,
    agent_cfg: dict,
) -> tuple[int, object]:  # (exit_code, session)
    """Execute a free-form task with raw CLI tools. Returns (exit_code, session)."""
    from functools import partial

    full_description = description
    if prev_context:
        full_description = f"{description}\n\n---\n## Context from previous steps\n{prev_context}"

    fastmarket_tools = agent_cfg.get("fastmarket_tools", {})
    system_commands = agent_cfg.get("system_commands", [])
    allowed = list(fastmarket_tools.keys()) + system_commands

    task_config = TaskConfig(
        fastmarket_tools=fastmarket_tools,
        system_commands=system_commands,
        allowed_commands=allowed,
        max_iterations=agent_cfg.get("max_iterations", 20),
        default_timeout=agent_cfg.get("default_timeout", 60),
        llm_timeout=0,
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
    return exit_code, loop.session


def _try_auto_learn(skill, params, session, subdir, session_path, model, compact):
    """Best-effort auto-learn — never raises."""
    try:
        from common.core.config import load_tool_config, requires_common_config
        from common.llm.registry import discover_providers, get_default_provider_name
        from core.runner import _run_auto_learn_from_skill

        requires_common_config("skill", ["llm"])
        config = load_tool_config("skill")
        providers = discover_providers(config)
        provider = providers.get(get_default_provider_name(config))
        if provider:
            _run_auto_learn_from_skill(
                skill=skill,
                params=params,
                workdir=subdir,
                provider=provider,
                model=model,
                session=session,
                session_path=session_path,
            )
    except Exception as exc:
        logger.warning("auto_learn_failed", skill=skill.name, error=str(exc))


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
) -> RouterState:
    """Orchestrate skills and free-form tasks to achieve a goal.

    Args:
        interaction: Plugin for user interaction. Defaults to CLIInteractionPlugin.
    """
    from commands.setup import init_skill_agent_config
    from common.core.config import load_tool_config
    from common.llm.registry import get_default_provider_name

    if interaction is None:
        interaction = CLIInteractionPlugin()

    # Resolve provider name from the provider object's config
    try:
        config = load_tool_config("apply")
        provider_name = get_default_provider_name(config)
    except Exception:
        # Fallback: try to get name from provider object
        provider_name = getattr(provider, "name", "default")

    agent_cfg = init_skill_agent_config()
    state = RouterState(goal=goal, attempts=[], iteration=0, max_iterations=max_iterations)
    skills = discover_skills(get_skills_dir())
    workdir_path = Path(workdir).expanduser().resolve()

    if not skills:
        state.failed = True
        state.failure_reason = "No skills available"
        return state

    prev_context = ""

    while state.iteration < max_iterations and not state.done and not state.failed:
        state.iteration += 1

        # --- Plan ---
        try:
            plan = _call_plan(state, provider, model, skills)
        except Exception as exc:
            state.failed = True
            state.failure_reason = f"Planner failed: {exc}"
            break

        action = plan.get("action")
        logger.debug("router_plan", iteration=state.iteration, action=action)

        # --- Done / Fail ---
        if action == "done":
            state.done = True
            state.final_result = str(plan.get("reason", "Goal achieved"))
            break

        if action == "fail":
            state.failed = True
            state.failure_reason = str(plan.get("reason", "Router declared failure"))
            break

        # --- Ask user ---
        if action == "ask":
            question = str(plan.get("question", "What should I do next?"))
            reason = str(plan.get("reason", ""))
            logger.info("router_asking_user", question=question, reason=reason)

            answer = interaction.ask(question)

            # Inject answer back into goal context as a user turn in history
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
            )
            state.attempts.append(attempt)
            prev_context = attempt.context
            if verbose:
                _print_attempt(attempt)
            continue

        # --- Run skill ---
        if action == "run":
            skill_name = str(plan.get("skill_name", "")).strip()
            params = {str(k): str(v) for k, v in (plan.get("params") or {}).items()}
            context_hint = str(plan.get("context_hint", ""))

            matched = next((s for s in skills if s.name == skill_name), None)
            if not matched:
                state.failed = True
                state.failure_reason = f"Planner returned unknown skill: {skill_name}"
                break

            failed_count = sum(
                1 for a in state.attempts
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
                )
                state.attempts.append(attempt)
                if verbose:
                    _print_attempt(attempt)
                continue

            subdir = _make_subdir(workdir_path, state.iteration, skill_name)
            logger.info("router_run_skill", skill=skill_name, subdir=str(subdir))

            exit_code, session = _run_skill(
                skill=matched,
                params=params,
                subdir=subdir,
                provider_name=provider_name,
                model=model,
                skill_timeout=skill_timeout,
                auto_learn=auto_learn,
                compact=compact,
                prev_context=prev_context,
            )

            session_output = _session_to_text(session)
            label = skill_name

        # --- Generic task ---
        elif action == "task":
            description = str(plan.get("description", "")).strip()
            context_hint = str(plan.get("context_hint", ""))
            params = {}

            if not description:
                state.failed = True
                state.failure_reason = "Planner issued 'task' action with no description"
                break

            subdir = _make_subdir(workdir_path, state.iteration, "task")
            logger.info("router_run_task", subdir=str(subdir))

            exit_code, session = _run_task(
                description=description,
                subdir=subdir,
                provider_name=provider_name,
                model=model,
                prev_context=prev_context,
                agent_cfg=agent_cfg,
            )

            session_output = _session_to_text(session)
            label = f"(task) {description[:60]}"

        else:
            state.failed = True
            state.failure_reason = f"Invalid planner action: {action}"
            break

        # --- Distill results (shared for "run" and "task") ---
        try:
            runner_summary = _call_runner_summary(label, params, session_output, provider, model)
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

        prev_context = new_context

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
            subdir=subdir,
        )
        state.attempts.append(attempt)
        if verbose:
            _print_attempt(attempt)

    if not state.done and not state.failed and state.iteration >= max_iterations:
        state.failed = True
        state.failure_reason = f"Max iterations ({max_iterations}) reached without completion"

    return state
