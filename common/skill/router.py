from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from common import structlog
from common.core.paths import get_cache_dir, get_skills_dir
from common.llm.base import LLMRequest
from common.skill.skill import Skill, discover_skills

logger = structlog.get_logger(__name__)

PLAN_PROMPT = """You are a skill orchestrator. Your job is to achieve a goal by
selecting and sequencing skills, one at a time.

## Goal
{goal}

## Available Skills
{skills_list}

## History
{history}

## Instructions

Decide what to do next. You must return ONLY a JSON object:

If you need to run a skill:
{{
  "action": "run",
  "skill_name": "the-skill-name",
  "params": {{"key": "value"}},
  "reason": "one sentence why"
}}

If the goal is fully achieved:
{{
  "action": "done",
  "reason": "one sentence summary of what was accomplished"
}}

If the goal cannot be achieved (repeated failures, missing capability):
{{
  "action": "fail",
  "reason": "one sentence explanation of why"
}}

Rules:
- Only use skills from the Available Skills list
- If a previous attempt failed, try a different approach or different params
- Never repeat the exact same skill+params that already failed
- Params must be concrete values, not placeholders
- If a skill produced output that a next skill needs, include the relevant
  part directly in that skill's params
"""

DISTILL_PROMPT = """You have just executed a skill. Read the session output and
extract what matters for the next step.

## Skill executed
{skill_name} with params: {params}

## Session output (truncated to last {max_chars} chars if long)
{session_output}

## Instructions

Write a concise summary (max 10 lines) that captures:
- What was accomplished (specific facts, data, results)
- What the output contains (e.g. "a marketing analysis in French, 500 words")
- Any errors or problems encountered
- Any data that will likely be needed by the next skill

Be specific. Include actual values (URLs, IDs, counts, key findings).
Do NOT include general observations or meta-commentary.
Output plain text, no headers, no JSON.
"""


@dataclass
class SkillAttempt:
    skill_name: str
    params: dict[str, str]
    exit_code: int
    distilled_result: str
    success: bool
    iteration: int


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
        return "No skills executed yet."

    lines = []
    for a in attempts:
        status = "✓ success" if a.success else "✗ failed"
        params_str = ", ".join(f"{k}={v}" for k, v in a.params.items())
        lines.append(f"Step {a.iteration}: {a.skill_name}({params_str}) → {status}")
        lines.append(f"  Result: {a.distilled_result}")
    return "\n".join(lines)


def _make_session_path(workdir: str, iteration: int) -> Path:
    cache = get_cache_dir() / "skill-router"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"session-{iteration:02d}.yaml"


def _execute_skill(
    skill_name: str,
    params: dict[str, str],
    workdir: str,
    timeout: int,
    session_file: Path,
) -> int:
    cmd = ["skill", "apply", skill_name]
    for k, v in params.items():
        cmd.append(f"{k}={v}")
    cmd += ["--save-session", str(session_file)]
    if workdir and workdir != ".":
        cmd += ["--workdir", workdir]

    result = subprocess.run(cmd, timeout=timeout)
    return result.returncode


def _read_session(session_file: Path) -> str:
    if not session_file.exists():
        return "(no session file found)"

    data = yaml.safe_load(session_file.read_text(encoding="utf-8")) or {}

    parts = []
    for turn in data.get("turns", []):
        if turn.get("role") == "assistant" and turn.get("content"):
            parts.append(f"ASSISTANT: {turn['content'][:500]}")
        for tc in turn.get("tool_calls", []):
            cmd = tc.get("arguments", {}).get("command", "")
            stdout = tc.get("stdout", "")[:300]
            stderr = tc.get("stderr", "")[:200]
            exit_code = tc.get("exit_code", "?")
            parts.append(f"CMD [{exit_code}]: {cmd}")
            if stdout:
                parts.append(f"  OUT: {stdout}")
            if stderr and exit_code != 0:
                parts.append(f"  ERR: {stderr}")

    combined = "\n".join(parts)
    return combined[:3000]


def _call_plan(state: RouterState, provider, model: str | None, skills: list[Skill]) -> dict:
    prompt = PLAN_PROMPT.format(
        goal=state.goal,
        skills_list=build_skills_list(skills),
        history=_format_history(state.attempts),
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=500)
    response = provider.complete(req)
    data = json.loads((response.content or "").strip())
    if not isinstance(data, dict):
        raise ValueError("Planner returned non-object JSON")
    return data


def _call_distill(
    skill_name: str,
    params: dict[str, str],
    session_output: str,
    provider,
    model: str | None,
    max_chars: int = 3000,
) -> str:
    prompt = DISTILL_PROMPT.format(
        skill_name=skill_name,
        params=params,
        session_output=session_output[-max_chars:],
        max_chars=max_chars,
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.3, max_tokens=500)
    response = provider.complete(req)
    return (response.content or "").strip()


def _print_attempt(attempt: SkillAttempt) -> None:
    status = "success" if attempt.success else "failed"
    params = ", ".join(f"{k}={v}" for k, v in attempt.params.items())
    print(f"[router] step {attempt.iteration}: {attempt.skill_name} ({params}) -> {status}")
    print(f"[router] distilled: {attempt.distilled_result[:300]}")


def run_router(
    goal: str,
    provider,
    model: str | None = None,
    workdir: str = ".",
    max_iterations: int = 10,
    skill_timeout: int = 300,
    retry_limit: int = 2,
    verbose: bool = False,
) -> RouterState:
    state = RouterState(goal=goal, attempts=[], iteration=0, max_iterations=max_iterations)
    skills = discover_skills(get_skills_dir())

    if not skills:
        state.failed = True
        state.failure_reason = "No skills available"
        return state

    while state.iteration < max_iterations and not state.done and not state.failed:
        state.iteration += 1

        try:
            plan = _call_plan(state, provider, model, skills)
        except Exception as exc:
            state.failed = True
            state.failure_reason = f"Planner failed: {exc}"
            break

        action = plan.get("action")
        if action == "done":
            state.done = True
            state.final_result = str(plan.get("reason", "Goal achieved"))
            break

        if action == "fail":
            state.failed = True
            state.failure_reason = str(plan.get("reason", "Router declared failure"))
            break

        if action != "run":
            state.failed = True
            state.failure_reason = f"Invalid planner action: {action}"
            break

        skill_name = str(plan.get("skill_name", "")).strip()
        params = plan.get("params", {})
        if not isinstance(params, dict):
            params = {}
        params = {str(k): str(v) for k, v in params.items()}

        matched = next((s for s in skills if s.name == skill_name), None)
        if not matched:
            state.failed = True
            state.failure_reason = f"Planner returned unknown skill: {skill_name}"
            break

        failed_count = sum(1 for a in state.attempts if a.skill_name == skill_name and not a.success)
        if failed_count >= retry_limit:
            attempt = SkillAttempt(
                skill_name=skill_name,
                params=params,
                exit_code=1,
                distilled_result=f"Skipped: retry limit ({retry_limit}) reached for {skill_name}",
                success=False,
                iteration=state.iteration,
            )
            state.attempts.append(attempt)
            if verbose:
                _print_attempt(attempt)
            continue

        session_file = _make_session_path(workdir, state.iteration)
        exit_code = _execute_skill(skill_name, params, workdir, skill_timeout, session_file)
        session_output = _read_session(session_file)

        try:
            distilled = _call_distill(skill_name, params, session_output, provider, model)
        except Exception as exc:
            distilled = f"Distillation failed: {exc}"

        attempt = SkillAttempt(
            skill_name=skill_name,
            params=params,
            exit_code=exit_code,
            distilled_result=distilled,
            success=(exit_code == 0),
            iteration=state.iteration,
        )
        state.attempts.append(attempt)
        if verbose:
            _print_attempt(attempt)

    if not state.done and not state.failed and state.iteration >= max_iterations:
        state.failed = True
        state.failure_reason = f"Max iterations ({max_iterations}) reached without completion"

    return state
