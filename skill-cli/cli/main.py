from __future__ import annotations

import logging
import os
from pathlib import Path

import click

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
)
from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config
from common.core.registry import discover_commands, discover_plugins
from common.learn import (
    LEARN_COMPACTING_PROMPT_TEMPLATE,
    SKILL_EXTRACTION_PROMPT_TEMPLATE,
    SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE,
)
from common.prompt import register_commands, get_prompt_manager

requires_common_config("skill", [])

main = create_cli_group("skill")
_TOOL_ROOT = Path(__file__).resolve().parents[1]
_prompt_manager = None

SKILL_DEFAULT_PROMPTS = {
    "agent": DEFAULT_AGENT_PROMPT_TEMPLATE,
    "preparation": DEFAULT_PREPARATION_PROMPT,
    "evaluation": DEFAULT_EVALUATION_PROMPT,
    "plan": DEFAULT_PLAN_PROMPT,
    "skill-from-description": SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE,
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
- If no lessons were learned (trivial task), write: `# Lessons Learned\n\nERROR: No lessons learned\n\n_No lessons recorded for this run._`
- Output ONLY the markdown content, no preamble, no code fences
- ONLY new lessons learned should be included, not repeated content.
""",
    "learn-compacting": LEARN_COMPACTING_PROMPT_TEMPLATE,
    "skill-extraction": SKILL_EXTRACTION_PROMPT_TEMPLATE,
    "create-skill-template": """---
name: {skill_name}
description: {skill_description}

---

# {skill_name} Skill

## When to use this skill
Describe when this skill should be used.

## Instructions
Provide step-by-step instructions for using this skill.

## Examples
Include examples of how to use this skill.
""",
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
