"""
Unified learning templates for auto-learn functionality.

This module provides:
- learn_analysis_prompt: The prompt that tells LLM HOW to analyze sessions
- learn_result_template: The expected format/structure of LEARN.md output
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common import structlog
from common.core.paths import get_skills_dir

logger = structlog.get_logger(__name__)

MAX_LEARN_LINES = 80


LEARN_ANALYSIS_PROMPT_TEMPLATE = """You are analyzing an agentic task session to extract lessons for future runs of the same skill.

## Session Summary
Task: {task_description}
Skill: {skill_name}
Outcome: {outcome}
Iterations used: {iterations_used} / {max_iterations}
Parameters: {params_summary}

## Full Session Log
{session_log}

---

## Your job

Write a LEARN.md file for the skill '{skill_name}'. This file will be injected into the system prompt of future task runs using this skill, so it must be:

1. **Actionable** — specific commands, flags, paths, patterns that work
2. **Concise** — maximum 30 lines total
3. **Focused on failures** — what went wrong is more valuable than what worked
4. **Tool-specific** — name the exact commands and arguments

### LEARN.md structure (use exactly this format):

{learn_result_template}

Rules:
- Each bullet must be concrete and specific to THIS skill/task
- Do NOT include generic advice (e.g., "check outputs carefully")
- Do NOT include anything already obvious from the SKILL.md instructions
- If the task succeeded on the first try with no errors, write only a "What Works" section with the successful approach
- If no lessons were learned (trivial task), write: `# Lessons Learned\n\n_No lessons recorded for this run._`
- Output ONLY the markdown content, no preamble, no code fences
"""

LEARN_RESULT_TEMPLATE = """```markdown
# Lessons Learned for {skill_name}

## What Works
- [specific command or approach that succeeded]

## What to Avoid
- [specific command/flag/pattern] — causes [specific error or problem]

## Useful Commands for This Skill
- `[exact command with args]` — [what it does in this context]

## Common Errors and Fixes
- Error: `[exact error message snippet]` → Fix: [what to do]
```"""

COMPRESS_PROMPT = """The following LEARN.md file has grown too large. Compress it into a single clean LEARN.md keeping only the most valuable and non-redundant lessons. Maximum {max_lines} lines. Same format.

{content}

Output ONLY the compressed markdown, no preamble."""

LEARN_COMPACTING_PROMPT_TEMPLATE = """The following LEARN.md file contains multiple learning sessions. Compress them into a single clean LEARN.md keeping only the most valuable and non-redundant lessons. Maximum {max_lines} lines.

## Current LEARN.md:
{content}

## Your job:
Analyze all the learning sessions and create ONE consolidated LEARN.md that:
- Keeps the most actionable insights
- Removes redundant entries
- Maintains the exact format below

### Output format:
{learn_result_template}

Output ONLY the markdown content, no preamble, no code fences."""


def get_learn_analysis_prompt(config: dict | None = None) -> str:
    """Get the learn analysis prompt from config or return default."""
    if config:
        template = config.get("learn_analysis_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_ANALYSIS_PROMPT_TEMPLATE


def get_learn_result_template(config: dict | None = None) -> str:
    """Get the learn result template from config or return default."""
    if config:
        template = config.get("learn_result_template")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_RESULT_TEMPLATE


def get_learn_compacting_prompt(config: dict | None = None) -> str:
    """Get the learn compacting prompt from config or return default."""
    if config:
        template = config.get("learn_compacting_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_COMPACTING_PROMPT_TEMPLATE


def format_session_log(session) -> str:
    """Format session turns into a compact log for LLM analysis."""
    lines = []
    for i, turn in enumerate(session.turns):
        if turn.role == "user" and i == 0:
            continue

        if hasattr(turn, "tool_calls") and turn.tool_calls:
            for tc in turn.tool_calls:
                cmd = (
                    tc.arguments.get("command", "") if hasattr(tc, "arguments") else ""
                )
                reason = tc.explanation or (
                    tc.arguments.get("explanation", "")
                    if hasattr(tc, "arguments")
                    else ""
                )
                lines.append(f"→ CMD: {cmd}")
                if reason:
                    lines.append(f"  Reason: {reason}")
                lines.append(f"  Exit: {tc.exit_code}")
                if tc.stdout and tc.exit_code != 0:
                    lines.append(f"  Stdout: {tc.stdout[:300]}")
                if hasattr(tc, "stderr") and tc.stderr:
                    lines.append(f"  Stderr: {tc.stderr[:300]}")
        elif (
            hasattr(turn, "role")
            and turn.role == "assistant"
            and hasattr(turn, "content")
            and turn.content
        ):
            if i == len(session.turns) - 1:
                lines.append(f"→ FINAL: {turn.content[:200]}")

    return "\n".join(lines)


def analyze_session(
    session,
    skill_name: str,
    provider,
    model: str | None = None,
    learn_analysis_prompt: str | None = None,
    learn_result_template: str | None = None,
) -> str:
    """Analyze a session and return LEARN.md content as markdown."""
    from common.llm.base import LLMRequest

    try:
        analysis_prompt = learn_analysis_prompt or LEARN_ANALYSIS_PROMPT_TEMPLATE
        result_template = learn_result_template or LEARN_RESULT_TEMPLATE

        prompt = analysis_prompt.format(
            task_description=session.task_description,
            skill_name=skill_name,
            outcome="success" if session.exit_code == 0 else "failed",
            iterations_used=len(session.turns),
            max_iterations=session.max_iterations,
            params_summary=session.task_params or {},
            session_log=format_session_log(session),
            learn_result_template=result_template,
        )

        request = LLMRequest(
            prompt=prompt,
            model=model,
            temperature=0.1,
            max_tokens=1200,
        )
        response = provider.complete(request)
        content = (response.content or "").strip()
        return content or "# Lessons Learned\n\n_No lessons recorded for this run._"
    except Exception as exc:
        logger.warning("learn_analyze_failed", error=str(exc), skill=skill_name)
        return "# Lessons Learned\n\n_No lessons recorded for this run._"


def compress_learn_content(
    content: str,
    provider=None,
    model: str | None = None,
    use_compacting: bool = False,
    learn_result_template: str | None = None,
    max_lines: int = MAX_LEARN_LINES,
) -> str:
    """Compress LEARN.md content to keep it under MAX_LEARN_LINES.

    Args:
        content: The LEARN.md content to compress
        provider: LLM provider for compression
        model: LLM model to use
        use_compacting: If True, use the compacting prompt for multi-session consolidation
        learn_result_template: The result template format to use in the prompt
        max_lines: Maximum number of lines in the output (for compacting)
    """
    from common.llm.base import LLMRequest

    if provider is None:
        return "\n".join(content.splitlines()[:max_lines]).strip()

    result_template = learn_result_template or LEARN_RESULT_TEMPLATE

    try:
        if use_compacting:
            compacting_prompt = get_learn_compacting_prompt()
            prompt = compacting_prompt.format(
                content=content,
                learn_result_template=result_template,
                max_lines=max_lines,
            )
        else:
            prompt = COMPRESS_PROMPT.format(content=content, max_lines=max_lines)

        request = LLMRequest(
            prompt=prompt,
            model=model,
            temperature=0.0,
            max_tokens=1000,
        )
        response = provider.complete(request)
        text = (response.content or "").strip()
        return text or "\n".join(content.splitlines()[:max_lines]).strip()
    except Exception as exc:
        logger.warning("learn_compress_failed", error=str(exc))
        return "\n".join(content.splitlines()[:max_lines]).strip()


def update_learn_file(
    skill_name: str,
    new_content: str,
    merge: bool = True,
    provider=None,
    model: str | None = None,
    autocompact_lines: int | None = None,
    use_compacting: bool = False,
) -> Path:
    """Write or update the LEARN.md file for a skill.

    Args:
        skill_name: Name of the skill
        new_content: New LEARN.md content to add
        merge: If True, merge with existing content; if False, replace
        provider: LLM provider for compression/compaction
        model: LLM model to use
        autocompact_lines: If set, compact when exceeding this many lines (instead of MAX_LEARN_LINES)
        use_compacting: If True, use compacting prompt for multi-session consolidation
    """
    try:
        skill_dir = get_skills_dir() / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        learn_path = skill_dir / "LEARN.md"

        if not merge or not learn_path.exists():
            learn_path.write_text((new_content or "").strip() + "\n", encoding="utf-8")
            return learn_path

        existing = learn_path.read_text(encoding="utf-8")
        stamped = (
            f"\n\n---\n<!-- run: {datetime.utcnow().isoformat()} -->\n\n"
            f"{(new_content or '').strip()}\n"
        )
        merged = (existing.rstrip() + stamped).strip() + "\n"

        threshold = (
            autocompact_lines if autocompact_lines is not None else MAX_LEARN_LINES
        )
        if len(merged.splitlines()) > threshold:
            merged = compress_learn_content(
                merged,
                provider=provider,
                model=model,
                use_compacting=use_compacting,
                max_lines=threshold,
            )
            merged = merged.strip() + "\n"

        learn_path.write_text(merged, encoding="utf-8")
        return learn_path
    except Exception as exc:
        logger.warning("learn_update_failed", error=str(exc), skill=skill_name)
        fallback = get_skills_dir() / skill_name / "LEARN.md"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        if not fallback.exists():
            fallback.write_text(
                "# Lessons Learned\n\n_No lessons recorded for this run._\n",
                encoding="utf-8",
            )
        return fallback
