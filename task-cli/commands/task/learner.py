from __future__ import annotations

from datetime import datetime
from pathlib import Path

from common import structlog
from common.core.paths import get_skills_dir
from common.llm.base import LLMRequest
from core.session import Session

logger = structlog.get_logger(__name__)

MAX_LEARN_LINES = 80

LEARN_PROMPT_TEMPLATE = """You are analyzing an agentic task session to extract lessons for future runs of the same skill.

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

```markdown
# Lessons Learned for {skill_name}

## What Works
- [specific command or approach that succeeded]

## What to Avoid
- [specific command/flag/pattern] — causes [specific error or problem]

## Useful Commands for This Skill
- `[exact command with args]` — [what it does in this context]

## Common Errors and Fixes
- Error: `[exact error message snippet]` → Fix: [what to do]
```

Rules:
- Each bullet must be concrete and specific to THIS skill/task
- Do NOT include generic advice (e.g., "check outputs carefully")
- Do NOT include anything already obvious from the SKILL.md instructions
- If the task succeeded on the first try with no errors, write only a "What Works" section with the successful approach
- If no lessons were learned (trivial task), write: `# Lessons Learned\n\n_No lessons recorded for this run._`
- Output ONLY the markdown content, no preamble, no code fences
"""

COMPRESS_PROMPT = """The following LEARN.md file has grown too large. Compress it into a single clean LEARN.md keeping only the most valuable and non-redundant lessons. Maximum 30 lines. Same format.

{content}

Output ONLY the compressed markdown, no preamble."""


def _format_session_log(session: Session) -> str:
    """Format session turns into a compact log for LLM analysis."""
    lines = []
    for i, turn in enumerate(session.turns):
        if turn.role == "user" and i == 0:
            continue

        if turn.tool_calls:
            for tc in turn.tool_calls:
                cmd = tc.arguments.get("command", "")
                reason = tc.explanation or tc.arguments.get("explanation", "")
                lines.append(f"→ CMD: {cmd}")
                if reason:
                    lines.append(f"  Reason: {reason}")
                lines.append(f"  Exit: {tc.exit_code}")
                if tc.stdout and tc.exit_code != 0:
                    lines.append(f"  Stdout: {tc.stdout[:300]}")
                if tc.stderr:
                    lines.append(f"  Stderr: {tc.stderr[:300]}")
        elif turn.role == "assistant" and turn.content:
            if i == len(session.turns) - 1:
                lines.append(f"→ FINAL: {turn.content[:200]}")

    return "\n".join(lines)


def analyze_session(
    session: Session,
    skill_name: str,
    provider,
    model: str | None = None,
    learn_prompt_template: str | None = None,
) -> str:
    """Analyze a session and return LEARN.md content as markdown."""
    try:
        template = learn_prompt_template or LEARN_PROMPT_TEMPLATE
        prompt = template.format(
            task_description=session.task_description,
            skill_name=skill_name,
            outcome="success" if session.exit_code == 0 else "failed",
            iterations_used=len(session.turns),
            max_iterations=session.max_iterations,
            params_summary=session.task_params or {},
            session_log=_format_session_log(session),
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


def _compress_learn_content(content: str, provider=None, model: str | None = None) -> str:
    if provider is None:
        return "\n".join(content.splitlines()[:30]).strip()
    try:
        request = LLMRequest(
            prompt=COMPRESS_PROMPT.format(content=content),
            model=model,
            temperature=0.0,
            max_tokens=1000,
        )
        response = provider.complete(request)
        text = (response.content or "").strip()
        return text or "\n".join(content.splitlines()[:30]).strip()
    except Exception as exc:
        logger.warning("learn_compress_failed", error=str(exc))
        return "\n".join(content.splitlines()[:30]).strip()


def update_learn_file(
    skill_name: str,
    new_content: str,
    merge: bool = True,
    provider=None,
    model: str | None = None,
) -> Path:
    """Write or update the LEARN.md file for a skill."""
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

        if len(merged.splitlines()) > MAX_LEARN_LINES:
            merged = _compress_learn_content(merged, provider=provider, model=model)
            merged = merged.strip() + "\n"

        learn_path.write_text(merged, encoding="utf-8")
        return learn_path
    except Exception as exc:
        logger.warning("learn_update_failed", error=str(exc), skill=skill_name)
        fallback = get_skills_dir() / skill_name / "LEARN.md"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        if not fallback.exists():
            fallback.write_text("# Lessons Learned\n\n_No lessons recorded for this run._\n", encoding="utf-8")
        return fallback
