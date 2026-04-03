from __future__ import annotations

import logging
import os
from pathlib import Path

import click

from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config
from common.core.registry import discover_commands, discover_plugins
from common.prompt import register_commands, get_prompt_manager

requires_common_config("skill", [])

main = create_cli_group("skill")
_TOOL_ROOT = Path(__file__).resolve().parents[1]
_prompt_manager = None

SKILL_DEFAULT_PROMPTS = {
    "agent": """You are a skill execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in: `{workdir}`

You can read and write files in this directory. Relative paths are resolved from here.

---

{command_docs}

---

# How to Work

1. **Understand the task**: Break it down into clear steps
2. **Explore first**: Use `ls` and `cat` to understand what files exist
3. **Execute incrementally**: Run one command, check the result, then decide next step
4. **Handle errors**: If a command fails, read the error message and try a different approach
5. **Stay focused**: Only use commands that advance the task
6. **Finish clearly**: When done, summarize what you accomplished (without making tool calls)

# Critical Rules

- **Only use listed commands** - others will be rejected
- **Work within the directory** - you cannot escape `{workdir}`
- **Check outputs** - always verify command results before proceeding
- **Be efficient** - prefer one good command over many guesses
- **Ask for help** - if truly stuck, explain what you need
""",
    "preparation": """You are a skill orchestrator. Before entering the planning loop,
read the goal and available skills, then produce a structured execution plan.

## Goal
{goal}

## Available Skills
{skills_list}

## Your Task

Analyze the goal and available skills. Produce a JSON object with your plan:

```json
{{
  "plan": "step by step description of intended approach",
  "success_criteria": "concrete, observable description of what done looks like",
  "risks": "what could go wrong and how to handle it"
}}
```

IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\\") or use single quotes only when the outer string uses double quotes.

Be specific about the order of skills and what each step should accomplish.
""",
    "evaluation": """You are evaluating whether the last step brought us closer to the goal.

## Goal
{goal}

## Success Criteria
{success_criteria}

## History
{history}

## Last Step Result
{last_summary}

## Your Task

Determine if the last step satisfied the success criteria. Return a JSON object:

```json
{{
  "satisfied": true or false,
  "reason": "one sentence explaining your assessment",
  "suggestion": "if not satisfied, what to try next"
}}
```

IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\\") or use single quotes only when the outer string uses double quotes.

Be honest — if the goal isn't met, say so and suggest a different approach.""",
    "plan": """You are a skill orchestrator. Your job is to achieve a goal by
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
- IMPORTANT: Use proper JSON escaping. If you need to use quotes inside a string, escape them with backslash (\") or use single quotes only when the outer string uses double quotes
""",
    "skill-from-description": """You are creating a new skill from a task description.

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
- Output ONLY the JSON, no preamble, no code fences.""",
    "learn-analysis": """You are analyzing an agentic task session to extract lessons for future runs of the same skill.

## Session Summary
Task: {task_description}
Skill: {skill_name}
Outcome: {outcome}
Iterations used: {iterations_used} / {max_iterations}
Parameters: {params_summary}

## Full Session Log
{session_log}

{existing_learnings_block}

---

## Your job

Write a LEARN.md file for the skill '{skill_name}' with NEW LESSONS LEARNED. This file will be injected into the system prompt of future task runs using this skill, so it must be:

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
- ONLY new lessons learned should be included, not repeated content.
""",
    "learn-compacting": """The following LEARN.md file contains multiple learning sessions. Compress them into a single clean LEARN.md keeping only the most valuable and non-redundant lessons. Maximum {max_lines} lines.

## Current LEARN.md:
{content}

## Your job:
Analyze all the learning sessions and create ONE consolidated LEARN.md that:
- Keeps the most actionable insights
- Removes redundant entries
- Maintains the exact format below

### Output format:
{learn_result_template}

Output ONLY the markdown content, no preamble, no code fences.""",
    "skill-extraction": """You are creating a new skill from a session log.

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
- Output ONLY the JSON, no preamble, no code fences.""",
}


def _load() -> None:
    global _prompt_manager
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_tool_config("skill")
    plugin_manifests = {}
    if (_TOOL_ROOT / "plugins").exists():
        plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)

    _prompt_manager = get_prompt_manager("skill", SKILL_DEFAULT_PROMPTS)
    register_commands(main, "skill", SKILL_DEFAULT_PROMPTS)


def get_skill_prompt_manager():
    """Get the skill prompt manager for use in other modules."""
    return _prompt_manager

    @main.command("completion")
    @click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), required=False)
    def completion_cmd(shell):
        """Print shell completion activation instructions."""
        target_shell = shell
        if not target_shell:
            env_shell = os.environ.get("SHELL", "")
            if env_shell.endswith("bash"):
                target_shell = "bash"
            elif env_shell.endswith("zsh"):
                target_shell = "zsh"
            elif env_shell.endswith("fish"):
                target_shell = "fish"

        snippets = {
            "bash": '# Add to ~/.bashrc:\neval "$(_SKILL_COMPLETE=bash_source skill)"',
            "zsh": '# Add to ~/.zshrc:\neval "$(_SKILL_COMPLETE=zsh_source skill)"',
            "fish": "# Add to ~/.config/fish/completions/skill.fish:\n_SKILL_COMPLETE=fish_source skill | source",
        }

        if target_shell:
            click.echo(snippets[target_shell])
            return

        click.echo(snippets["bash"])
        click.echo()
        click.echo(snippets["zsh"])
        click.echo()
        click.echo(snippets["fish"])


_load()

if __name__ == "__main__":
    main()
