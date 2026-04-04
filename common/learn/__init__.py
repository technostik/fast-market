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

## Your job

Write a LEARN.md file for the skill '{skill_name}' with NEW LESSONS LEARNED.
A Lesson is what allow future run to avoid steps, errors or guesses and go directly to useful commands.
This file will be injected into the system prompt of future task runs using this skill, so it must be:

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
- ALWAYS extract lessons when there were command failures (non-zero exit codes), even if the task eventually succeeded
- If the task succeeded on the first try with ZERO errors, write only a "What Works" section with the successful approach
- If no commands were executed at all, write: `# Lessons Learned\n\nERROR: No commands executed\n\n_No lessons recorded for this run._`
- Output ONLY the markdown content, no preamble, no code fences
- ONLY new lessons learned should be included, not repeated content.
- MANDATORY: When task succeeded (exit code 0), you MUST state the EXACT successful command in "What Works" — the full command with all arguments, not a description of the process. Example: "The correct command is `guess doit again <INPUT>`" not "Use `guess --help` to discover the command"
- MANDATORY: If a command succeeded, the "What Works" section MUST contain the literal command string (e.g., `guess doit again hello`), not advice like "read help first"
- Generalize specific values from errors — use placeholders like `<INPUT>` instead of concrete values like `baseline1`
- Prioritize OUTCOME over PROCESS — capture WHAT WORKED (the command), not HOW YOU FOUND IT (reading help)

---

## Session to Analayse
Task: {task_description}
Skill: {skill_name}
Outcome: {outcome}
Errors: {error_count}
Iterations used: {iterations_used} / {max_iterations}
Parameters: {params_summary}

## Full Session Log
{session_log}

{existing_learnings_block}


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


SKILL_EXTRACTION_PROMPT_TEMPLATE = """You are creating a new skill from a session log.

## Session Summary
Task: {task_description}
Outcome: {outcome}
Iterations used: {iterations_used} / {max_iterations}
Parameters: {params_summary}

## Commands Executed
{session_log}

---

Your job is to create a SKILL.md file. Output ONLY a JSON object:

```json
{{
  "name": "skill-name-in-slug-format",
  "description": "2-3 sentences describing what this skill does",
  "body": "Step-by-step instructions derived from the commands above. Use present tense, be concise and actionable."
}}
```

Rules:
- name must be lowercase with hyphens (e.g., "extract-video-metadata")
- description should be general enough to know when to use this skill
- body should contain the actual instructions someone would follow
- Extract patterns from commands, not just list them
- If the task failed, focus on what would make it succeed
- Output ONLY the JSON, no preamble, no code fences."""

SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE = """You are creating a new skill from a task description.

## Task Description
{task_description}

## Available Tools
{tools_description}

## Existing Skills
{existing_skills}

---

Your job is to create a SKILL.md file. Output ONLY a JSON object:

```json
{{
  "name": "skill-name-in-slug-format",
  "description": "2-3 sentences describing when to use this skill",
  "when_to_use": "One sentence on when this skill is appropriate",
  "body": "Step-by-step instructions. Use present tense, be concise and actionable."
}}
```

Rules:
- name must be lowercase with hyphens (e.g., "extract-video-metadata")
- description should explain what the skill does
- when_to_use should help decide when to pick this skill vs others
- body should contain the actual instructions someone would follow
- Consider what tools the skill will need and include relevant commands
- Output ONLY the JSON, no preamble, no code fences."""


def get_learn_analysis_prompt(config: dict | None = None) -> str:
    """Get the learn analysis prompt from config or cached PromptManager."""
    from common.prompt import get_cached_manager

    manager = get_cached_manager("skill")
    if manager:
        override = manager.get("learn-analysis")
        if override:
            return override

    if config:
        template = config.get("learn_analysis_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_ANALYSIS_PROMPT_TEMPLATE


def get_learn_result_template(config: dict | None = None) -> str:
    """Get the learn result template from config."""
    if config:
        template = config.get("learn_result_template")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_RESULT_TEMPLATE


def get_learn_compacting_prompt(config: dict | None = None) -> str:
    """Get the learn compacting prompt from config or cached PromptManager."""
    from common.prompt import get_cached_manager

    manager = get_cached_manager("skill")
    if manager:
        override = manager.get("learn-compacting")
        if override:
            return override

    if config:
        template = config.get("learn_compacting_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return LEARN_COMPACTING_PROMPT_TEMPLATE


def get_skill_extraction_prompt(config: dict | None = None) -> str:
    """Get the skill extraction prompt from config or cached PromptManager."""
    from common.prompt import get_cached_manager

    manager = get_cached_manager("skill")
    if manager:
        override = manager.get("skill-extraction")
        if override:
            return override

    if config:
        template = config.get("skill_extraction_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return SKILL_EXTRACTION_PROMPT_TEMPLATE


def get_skill_from_description_prompt(config: dict | None = None) -> str:
    """Get the skill from description prompt from config or cached PromptManager."""
    from common.prompt import get_cached_manager

    manager = get_cached_manager("skill")
    if manager:
        override = manager.get("skill-from-description")
        if override:
            return override

    if config:
        template = config.get("skill_from_description_prompt")
        if isinstance(template, str) and template.strip():
            return template
    return SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE


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
                if tc.stderr:
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
    existing_learn_content: str | None = None,
    temperature: float | None = None,
) -> tuple[str, str]:
    """Analyze a session and return LEARN.md content as markdown.

    Returns:
        Tuple of (learn_content, full_prompt) for debugging purposes.
    """
    from common.llm.base import LLMRequest

    try:
        analysis_prompt = learn_analysis_prompt or LEARN_ANALYSIS_PROMPT_TEMPLATE
        result_template = learn_result_template or LEARN_RESULT_TEMPLATE

        if existing_learn_content:
            existing_block = f"""## Existing Learnings
{existing_learn_content}

---

**IMPORTANT:** Only write what is NEWLY learned in this session. Do NOT repeat what's already captured above."""
        else:
            existing_block = ""

        prompt = analysis_prompt.format(
            task_description=session.task_description,
            skill_name=skill_name,
            outcome="success" if session.exit_code == 0 else "failed",
            error_count=session.metrics_dict().get("error_count", 0),
            iterations_used=session.metrics_dict().get(
                "iterations_used", len(session.turns)
            ),
            max_iterations=session.max_iterations,
            params_summary=session.task_params or {},
            session_log=format_session_log(session),
            learn_result_template=result_template,
            existing_learnings_block=existing_block,
        )

        request = LLMRequest(
            prompt=prompt,
            model=model,
            temperature=temperature if temperature is not None else 0.0,
            max_tokens=4096,
        )
        response = provider.complete(request)
        content = (response.content or "").strip()
        logger.info(
            "learn_analyze_response",
            content_len=len(content),
            has_content=bool(content),
        )
        default_content = f"# Lessons Learned\n\nERROR: Failed to generate lessons (empty response)\n\n_No lessons recorded for this run._"
        return content or default_content, prompt
    except Exception as exc:
        logger.warning(
            "learn_analyze_failed", error=str(exc), skill=skill_name, model=model
        )
        import traceback

        logger.warning("learn_analyze_traceback", traceback=traceback.format_exc())
        default_content = (
            f"# Lessons Learned\n\nERROR: {exc}\n\n_No lessons recorded for this run._"
        )
        return default_content, ""


def compress_learn_content(
    content: str,
    provider=None,
    model: str | None = None,
    use_compacting: bool = False,
    learn_result_template: str | None = None,
    max_lines: int = MAX_LEARN_LINES,
    temperature: float | None = None,
) -> str:
    """Compress LEARN.md content to keep it under MAX_LEARN_LINES.

    Args:
        content: The LEARN.md content to compress
        provider: LLM provider for compression
        model: LLM model to use
        use_compacting: If True, use the compacting prompt for multi-session consolidation
        learn_result_template: The result template format to use in the prompt
        max_lines: Maximum number of lines in the output (for compacting)
        temperature: Temperature for LLM calls (defaults to 0.0)
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
            temperature=temperature if temperature is not None else 0.0,
            max_tokens=4096,
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
    temperature: float | None = None,
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
        temperature: Temperature for LLM calls (defaults to 0.0)
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
                temperature=temperature,
            )
            merged = merged.strip() + "\n"

        learn_path.write_text(merged, encoding="utf-8")
        return learn_path
    except Exception as exc:
        logger.warning("learn_update_failed", error=str(exc), skill=skill_name)
        import traceback

        logger.warning("learn_update_traceback", traceback=traceback.format_exc())
        fallback = get_skills_dir() / skill_name / "LEARN.md"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        if not fallback.exists():
            fallback.write_text(
                f"# Lessons Learned\n\nERROR: {exc}\n\n_No lessons recorded for this run._\n",
                encoding="utf-8",
            )
        return fallback


def extract_skill_from_session(
    session,
    provider,
    model: str | None = None,
    config: dict | None = None,
) -> tuple[str, str, str]:
    """Extract a skill definition from a session.

    Returns:
        Tuple of (name, description, body) for creating a SKILL.md.
    """
    from common.llm.base import LLMRequest

    prompt_template = get_skill_extraction_prompt(config)
    session_log = format_session_log(session)

    prompt = prompt_template.format(
        task_description=session.task_description,
        outcome="success" if session.exit_code == 0 else "failed",
        iterations_used=len(session.turns),
        max_iterations=session.max_iterations,
        params_summary=session.task_params or {},
        session_log=session_log,
    )

    request = LLMRequest(
        prompt=prompt,
        model=model,
        temperature=0.0,
        max_tokens=4096,
    )
    response = provider.complete(request)
    content = (response.content or "").strip()

    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]).strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        import json

        data = json.loads(content)
        name = data.get("name", "new-skill")
        description = data.get("description", "")
        body = data.get("body", "")
        return name, description, body
    except json.JSONDecodeError as exc:
        logger.warning("skill_extraction_parse_failed", content=content[:500])
        raise ValueError(f"Failed to parse skill extraction JSON: {exc}") from exc


def extract_skill_from_description(
    task_description: str,
    tools_description: str,
    existing_skills: str,
    provider,
    model: str | None = None,
    config: dict | None = None,
) -> tuple[str, str, str, str]:
    """Extract a skill definition from a task description.

    Returns:
        Tuple of (name, description, when_to_use, body) for creating a SKILL.md.
    """
    from common.llm.base import LLMRequest

    prompt_template = get_skill_from_description_prompt(config)

    prompt = prompt_template.format(
        task_description=task_description,
        tools_description=tools_description,
        existing_skills=existing_skills,
    )

    request = LLMRequest(
        prompt=prompt,
        model=model,
        temperature=0.0,
        max_tokens=4096,
    )
    response = provider.complete(request)
    content = (response.content or "").strip()

    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]).strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        import json

        data = json.loads(content)
        name = data.get("name", "new-skill")
        description = data.get("description", "")
        when_to_use = data.get("when_to_use", "")
        body = data.get("body", "")
        return name, description, when_to_use, body
    except json.JSONDecodeError as exc:
        logger.warning("skill_from_description_parse_failed", content=content[:500])
        raise ValueError(f"Failed to parse skill from description JSON: {exc}") from exc
