from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from common import structlog
from common.core.paths import get_cache_dir, get_skills_dir
from common.llm.base import LLMRequest
from common.rt_subprocess import rt_subprocess
from core.skill import Skill, discover_skills

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
  "reason": "one sentence why",
  "context_hint": "The next skill will need X, Y, Z from this result",
  "copy_from": [
    {{"subdir": "01_skill-name", "files": ["output.json"]}}
  ]
}}

- context_hint (optional): one sentence describing what the NEXT skill will need from this result
- copy_from (optional): list of previous subdirs and files to copy into the next skill's directory
  - Use this for large/binary files or outputs that should be physically present
  - For small outputs, prefer passing via params or context instead

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
- Use subdir paths from history to reference previous outputs
- Prefer passing small outputs via params or context; use copy_from for large/binary files
"""

RUNNER_SUMMARY_PROMPT = """Write a concise summary (max 15 lines) for the orchestrator:
- Did it succeed or fail?
- What approach was used?
- What errors occurred?
- What files or outputs were produced (names only, not contents)?
Do NOT include file contents or large data.

## Skill executed
{skill_name} with params: {params}

## Session output (truncated to last {max_chars} chars if long)
{session_output}
"""

CONTEXT_EXTRACT_PROMPT = """You are preparing context for the NEXT skill in a pipeline.

## Goal of the overall task
{goal}

## Skill just executed
{skill_name} with params: {params}

## Session output (truncated to last {max_chars} chars if long)
{session_output}

## What the next step will likely need
{next_step_hint}

Extract ONLY what a downstream skill will need to do its job.
Include: key data, results, extracted content, file contents if small (<200 lines).
For large files: include the first 50 lines and note the full path.
Be specific. No meta-commentary.
"""


@dataclass
class SkillAttempt:
    skill_name: str
    params: dict[str, str]
    exit_code: int
    runner_summary: str
    context: str
    context_hint: str
    success: bool
    iteration: int
    subdir: Path
    copied_files: list[str]


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
        subdir_name = a.subdir.name if a.subdir else "N/A"
        lines.append(f"Step {a.iteration}: {a.skill_name}({params_str}) → {status}")
        lines.append(f"  Subdir: {subdir_name}")
        if a.copied_files:
            lines.append(f"  Copied from previous: {', '.join(a.copied_files)}")
        lines.append(f"  Summary: {a.runner_summary[:200]}")
    return "\n".join(lines)


def _make_session_path(workdir: str, iteration: int) -> Path:
    cache = get_cache_dir() / "skill-router"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"session-{iteration:02d}.yaml"


def _copy_context_files(
    copy_from: list[dict],
    workdir: Path,
    dest: Path,
) -> list[str]:
    copied = []
    for item in copy_from:
        subdir_name = item.get("subdir", "")
        files = item.get("files", [])
        src_subdir = workdir / subdir_name
        if not src_subdir.exists():
            logger.warning(
                "copy_from_subdir_not_found",
                subdir=subdir_name,
                expected_path=str(src_subdir),
            )
            continue
        for filename in files:
            src_file = src_subdir / filename
            if not src_file.exists():
                logger.warning(
                    "copy_from_file_not_found",
                    subdir=subdir_name,
                    file=filename,
                    expected_path=str(src_file),
                )
                continue
            dest_file = dest / filename
            dest_file.write_bytes(src_file.read_bytes())
            copied.append(filename)
            logger.debug(
                "copied_context_file",
                src=str(src_file),
                dest=str(dest_file),
            )
    return copied


def _execute_skill(
    skill_name: str,
    params: dict[str, str],
    workdir: str,
    timeout: int,
    session_file: Path,
    auto_learn: bool = False,
    compact: bool = False,
    router_context: str | None = None,
) -> int:
    cmd = ["skill", "apply", skill_name]
    for k, v in params.items():
        cmd.append(f"{k}={v}")
    if router_context:
        cmd.append(f"_router_context={router_context}")
    cmd += ["--save-session", str(session_file)]
    if workdir and workdir != ".":
        cmd += ["--workdir", workdir]
    if auto_learn:
        cmd.append("--auto-learn")
    if compact:
        cmd.append("--compact")

    debug_enabled = os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
        "1",
        "true",
        "TRUE",
    }
    if debug_enabled:
        result = rt_subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        print(f"[router][exec] command={' '.join(cmd)} exit={result.returncode}")
    else:
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


def _call_plan(
    state: RouterState, provider, model: str | None, skills: list[Skill]
) -> dict:
    prompt = PLAN_PROMPT.format(
        goal=state.goal,
        skills_list=build_skills_list(skills),
        history=_format_history(state.attempts),
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.0, max_tokens=500)
    response = provider.complete(req)
    raw = (response.content or "").strip()
    debug_enabled = os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
        "1",
        "true",
        "TRUE",
    }
    if debug_enabled:
        print("[router][plan] model:", model or "(provider default)")
        print("[router][plan] prompt:\n", prompt[:4000])
        print("[router][plan] raw response:\n", raw if raw else "(empty)")

    if not raw:
        model_name = response.model or model or "unknown"
        finish_reason = (
            response.metadata.get("finish_reason") if response.metadata else None
        )
        raise ValueError(
            f"Planner returned empty response. "
            f"Model: {model_name}, finish_reason: {finish_reason}. "
            f"Enable SKILL_ROUTER_DEBUG_LLM=1 to print prompt/response details."
        )

    try:
        data = json.loads(raw)
    except Exception:
        cleaned = raw
        if "```" in cleaned:
            cleaned = cleaned.replace("```json", "```")
            parts = [p.strip() for p in cleaned.split("```") if p.strip()]
            json_candidates = [
                p for p in parts if p.startswith("{") and p.endswith("}")
            ]
            if json_candidates:
                cleaned = json_candidates[0]

        if not (cleaned.startswith("{") and cleaned.endswith("}")):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]

        try:
            data = json.loads(cleaned)
        except Exception as exc:
            raise ValueError(
                "Planner returned invalid JSON. "
                f"Raw response: {raw[:300]!r}. Parse error: {exc}"
            ) from exc

    if not isinstance(data, dict):
        raise ValueError("Planner returned non-object JSON")
    return data


def _call_runner_summary(
    skill_name: str,
    params: dict[str, str],
    session_output: str,
    provider,
    model: str | None,
    max_chars: int = 3000,
) -> str:
    prompt = RUNNER_SUMMARY_PROMPT.format(
        skill_name=skill_name,
        params=params,
        session_output=session_output[-max_chars:],
        max_chars=max_chars,
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.3, max_tokens=500)
    response = provider.complete(req)
    summary = (response.content or "").strip()
    debug_enabled = os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
        "1",
        "true",
        "TRUE",
    }
    if debug_enabled:
        print(f"[router][runner_summary] skill={skill_name} params={params}")
        print("[router][runner_summary] prompt:\n", prompt[:3000])
        print(
            "[router][runner_summary] raw response:\n",
            summary if summary else "(empty)",
        )

    if summary:
        return summary
    fallback = (session_output or "").strip()
    return fallback[:1000] if fallback else "(no summary)"


def _call_context_extract(
    goal: str,
    skill_name: str,
    params: dict[str, str],
    session_output: str,
    next_step_hint: str,
    provider,
    model: str | None,
    max_chars: int = 5000,
) -> str:
    prompt = CONTEXT_EXTRACT_PROMPT.format(
        goal=goal,
        skill_name=skill_name,
        params=params,
        session_output=session_output[-max_chars:],
        next_step_hint=next_step_hint
        or "Extract any useful data or results for the next skill.",
        max_chars=max_chars,
    )
    req = LLMRequest(prompt=prompt, model=model, temperature=0.3, max_tokens=1000)
    response = provider.complete(req)
    context = (response.content or "").strip()
    debug_enabled = os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
        "1",
        "true",
        "TRUE",
    }
    if debug_enabled:
        print(f"[router][context_extract] skill={skill_name} params={params}")
        print("[router][context_extract] prompt:\n", prompt[:3000])
        print(
            "[router][context_extract] raw response:\n",
            context if context else "(empty)",
        )

    if context:
        return context
    return ""


def _print_attempt(attempt: SkillAttempt) -> None:
    status = "success" if attempt.success else "failed"
    params = ", ".join(f"{k}={v}" for k, v in attempt.params.items())
    subdir_name = attempt.subdir.name if attempt.subdir else "N/A"
    print(
        f"[router] step {attempt.iteration}: {attempt.skill_name} ({params}) -> {status}"
    )
    print(f"[router] subdir: {subdir_name}")
    if attempt.copied_files:
        print(f"[router] copied files: {', '.join(attempt.copied_files)}")
    print(f"[router] summary: {attempt.runner_summary[:300]}")


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
) -> RouterState:
    state = RouterState(
        goal=goal, attempts=[], iteration=0, max_iterations=max_iterations
    )
    skills = discover_skills(get_skills_dir())
    workdir_path = Path(workdir).expanduser().resolve()

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

        if os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
            "1",
            "true",
            "TRUE",
        }:
            print(f"[router][plan] parsed action: {plan}")

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

        context_hint = str(plan.get("context_hint", ""))
        copy_from = plan.get("copy_from", [])
        if not isinstance(copy_from, list):
            copy_from = []

        matched = next((s for s in skills if s.name == skill_name), None)
        if not matched:
            state.failed = True
            state.failure_reason = f"Planner returned unknown skill: {skill_name}"
            break

        failed_count = sum(
            1 for a in state.attempts if a.skill_name == skill_name and not a.success
        )
        if failed_count >= retry_limit:
            attempt = SkillAttempt(
                skill_name=skill_name,
                params=params,
                exit_code=1,
                runner_summary=f"Skipped: retry limit ({retry_limit}) reached for {skill_name}",
                context="",
                context_hint=context_hint,
                success=False,
                iteration=state.iteration,
                subdir=Path(""),
                copied_files=[],
            )
            state.attempts.append(attempt)
            if verbose:
                _print_attempt(attempt)
            continue

        subdir_name = f"{state.iteration:02d}_{skill_name}"
        subdir = workdir_path / subdir_name
        subdir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "created_skill_subdir", subdir=str(subdir), iteration=state.iteration
        )

        copied_files = _copy_context_files(copy_from, workdir_path, subdir)
        if copied_files:
            logger.info("copied_context_files", files=copied_files, dest=str(subdir))

        prev_context = ""
        if state.attempts and state.attempts[-1].context:
            prev_context = state.attempts[-1].context

        session_file = _make_session_path(str(subdir), state.iteration)
        exit_code = _execute_skill(
            skill_name,
            params,
            str(subdir),
            skill_timeout,
            session_file,
            auto_learn=auto_learn,
            compact=compact,
            router_context=prev_context if prev_context else None,
        )
        session_output = _read_session(session_file)
        if os.environ.get("SKILL_ROUTER_DEBUG_LLM", "").strip() in {
            "1",
            "true",
            "TRUE",
        }:
            print(f"[router][session] file={session_file}")
            print("[router][session] summary:\n", session_output[:3000])

        try:
            runner_summary = _call_runner_summary(
                skill_name, params, session_output, provider, model
            )
        except Exception as exc:
            runner_summary = f"Summary failed: {exc}"

        try:
            context = _call_context_extract(
                goal,
                skill_name,
                params,
                session_output,
                context_hint,
                provider,
                model,
            )
        except Exception as exc:
            context = f"Context extraction failed: {exc}"

        attempt = SkillAttempt(
            skill_name=skill_name,
            params=params,
            exit_code=exit_code,
            runner_summary=runner_summary,
            context=context,
            context_hint=context_hint,
            success=(exit_code == 0),
            iteration=state.iteration,
            subdir=subdir,
            copied_files=copied_files,
        )
        state.attempts.append(attempt)
        if verbose:
            _print_attempt(attempt)

    if not state.done and not state.failed and state.iteration >= max_iterations:
        state.failed = True
        state.failure_reason = (
            f"Max iterations ({max_iterations}) reached without completion"
        )

    return state
