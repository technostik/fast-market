from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from functools import partial

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

## Success Criteria (what done looks like)
{success_criteria}

## Available Skills
{skills_list}

## History
{history}

## Instructions

Decide what to do next. Return ONLY a JSON object — no preamble, no code fences.

### Actions

Run a specific skill:
{{"action": "run", "skill_name": "the-skill-name", "params": {{"key": "value"}}, "reason": "one sentence why", "context_hint": "what the next skill will need"}}

Run a free-form task with raw CLI tools (when no skill fits or a skill failed):
{{"action": "task", "description": "detailed description", "reason": "one sentence why", "context_hint": "what the next step will need"}}

Ask the user a question (only when genuinely ambiguous):
{{"action": "ask", "question": "clear specific question", "reason": "one sentence why"}}

Goal fully achieved:
{{"action": "done", "reason": "one sentence summary of what was accomplished"}}

Goal cannot be achieved:
{{"action": "fail", "reason": "one sentence explanation of why"}}

### Rules
- Only use skills from the Available Skills list for "run" actions
- Use "task" when no skill fits OR when a skill failed and you want to improvise
- Use "ask" sparingly — only for genuine ambiguity, not when a skill fails
- Never repeat the exact same skill+params that already failed
- Params must be concrete values, not placeholders
- If a skill produced output the next skill needs, it is available in history as context
"""

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

PREPARATION_PROMPT = """You are a skill orchestrator. Before entering the planning loop,
read the goal and available skills, then produce a structured execution plan.

## Goal
{goal}

## Available Skills
{skills_list}

Return ONLY a JSON object — no preamble, no code fences:
{{"plan": "step by step description", "success_criteria": "concrete observable description of what done looks like", "risks": "what could go wrong"}}
"""

EVALUATION_PROMPT = """You are evaluating whether the last step satisfied the goal.

## Goal
{goal}

## Success Criteria
{success_criteria}

## History
{history}

## Last Step Result
{last_summary}

Return ONLY a JSON object — no preamble, no code fences:
{{"satisfied": true or false, "reason": "one sentence assessment", "suggestion": "if not satisfied, what to try next"}}

Be honest — if the goal is not met, say so.
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


def _make_subdir(run_root: Path, iteration: int, label: str) -> Path:
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
) -> dict:
    """Ask the planner what to do next. Returns dict with 'action' key."""
    template = prompt_template or PLAN_PROMPT
    prompt = template.format(
        goal=state.goal,
        skills_list=build_skills_list(skills),
        history=_format_history(state.attempts),
        success_criteria=state.success_criteria,
    )
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
) -> tuple[int, str, Path | None]:
    """Execute a skill using the same dispatch as `skill apply`.

    Returns (exit_code, session_output_text, session_path).
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
            auto_learn=False,  # handled below with the right provider instance
        )
        session_output = (result.stdout or "") + (result.stderr or "")
        exit_code = result.exit_code

        if auto_learn and session_path and session_path.exists():
            _try_auto_learn_from_path(
                skill=skill,
                params=effective_params,
                session_path=session_path,
                subdir=subdir,
                model=model,
                compact=compact,
            )

    # script/run: skills produce no session file
    if session_path and not session_path.exists():
        session_path = None

    logger.info(
        "skill_executed",
        skill=skill.name,
        exit_code=exit_code,
        mode="script" if skill.has_scripts else ("run" if skill.run else "prompt"),
    )
    return exit_code, session_output, session_path


def _try_auto_learn_from_path(
    skill: Skill,
    params: dict,
    session_path: Path,
    subdir: Path,
    model: str | None,
    compact: bool,
) -> None:
    """Load session from disk and run auto-learn. Never raises."""
    try:
        import yaml
        from common.agent.session import Session
        from common.core.config import load_tool_config
        from common.llm.registry import discover_providers, get_default_provider_name
        from core.runner import _run_auto_learn_from_skill

        data = yaml.safe_load(session_path.read_text())
        if not data:
            return
        session_obj = Session.from_dict(data)

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
                session=session_obj,
                session_path=session_path,
            )
    except Exception as exc:
        logger.warning("auto_learn_failed", skill=skill.name, error=str(exc))


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
) -> tuple[int, str, Path | None]:
    """Execute a free-form task in-process. Returns (exit_code, output, session_path)."""
    full_description = description
    if prev_context:
        full_description = (
            f"{description}\n\n---\n## Context from previous steps\n{prev_context}"
        )

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
        temperature=agent_cfg.get("default_temperature", 0.7),
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

    # Collect output from session turns
    session_output = _session_to_text(loop.session)

    session_path = None
    if save_session and loop.session:
        session_path = subdir / "task.session.yaml"
        loop.session.save(session_path)
        logger.info("task_session_saved", path=str(session_path))

    return exit_code, session_output, session_path


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
) -> RouterState:
    """Orchestrate skills and tasks to achieve a goal."""
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
    run_id = dt.utcnow().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_root = workdir_path / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    state = RouterState(
        goal=goal,
        attempts=[],
        iteration=0,
        max_iterations=max_iterations,
        run_root=run_root,
    )

    if not skills:
        state.failed = True
        state.failure_reason = "No skills available"
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
    except Exception as exc:
        state.failed = True
        state.failure_reason = f"Preparation failed: {exc}"
        return state

    session_files: list[Path] = []
    prev_context = ""

    # --- Planning loop ---
    while state.iteration < max_iterations and not state.done and not state.failed:
        state.iteration += 1

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

        # Terminal actions
        if action == "done":
            state.done = True
            state.final_result = str(plan.get("reason", "Goal achieved"))
            break

        if action == "fail":
            state.failed = True
            state.failure_reason = str(plan.get("reason", "Router declared failure"))
            break

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
                )
                state.attempts.append(attempt)
                if verbose:
                    _print_attempt(attempt)
                continue

            subdir = _make_subdir(run_root, state.iteration, skill_name)
            exit_code, session_output, session_path = _run_skill(
                skill=matched,
                params=params,
                subdir=subdir,
                provider_name=provider_name,
                model=model,
                auto_learn=auto_learn,
                compact=compact,
                prev_context=prev_context,
                save_session=save_session,
            )
            label = skill_name

        # Free-form task
        elif action == "task":
            description = str(plan.get("description", "")).strip()
            context_hint = str(plan.get("context_hint", ""))
            params = {}

            if not description:
                state.failed = True
                state.failure_reason = (
                    "Planner issued 'task' action with no description"
                )
                break

            subdir = _make_subdir(run_root, state.iteration, "task")
            exit_code, session_output, session_path = _run_task(
                description=description,
                subdir=subdir,
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
            raw_output=session_output,
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

    if save_session and session_files:
        _save_router_session(
            goal=goal,
            session_files=session_files,
            run_root=run_root,
            provider_name=provider_name,
            model=model,
            max_iterations=max_iterations,
            state=state,
        )

    return state
