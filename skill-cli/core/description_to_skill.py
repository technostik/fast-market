from __future__ import annotations

import sys

import click

from common import structlog
from common.core.config import (
    ConfigError,
    load_common_config,
    load_tool_config,
    requires_common_config,
)
from common.core.paths import get_skills_dir
from common.learn import extract_skill_from_description
from common.llm.registry import discover_providers, get_default_provider_name

from core.repl import prompt_confirm, prompt_free_text, prompt_with_options
from core.skill import discover_skills

logger = structlog.get_logger(__name__)


def load_tools_description(agent_config: dict) -> str:
    """Format available tools from agent config for the prompt."""
    lines = []

    fastmarket_tools = agent_config.get("fastmarket_tools", {})
    if fastmarket_tools:
        lines.append("## FastMarket Tools")
        for name, info in fastmarket_tools.items():
            desc = info.get("description", "No description")
            cmds = info.get("commands", [])
            lines.append(f"- **{name}**: {desc}")
            if cmds:
                lines.append(f"  Commands: {', '.join(cmds)}")

    system_commands = agent_config.get("system_commands", [])
    if system_commands:
        lines.append("\n## System Commands")
        lines.append(", ".join(system_commands))

    return "\n".join(lines) if lines else "No tools configured"


def load_existing_skills() -> str:
    """Format existing skills for the prompt."""
    skills = discover_skills(get_skills_dir())
    if not skills:
        return "No existing skills"

    lines = []
    for skill in skills:
        desc = skill.description or "No description"
        lines.append(f"- **{skill.name}**: {desc}")

    return "\n".join(lines)


def generate_skill_name(
    task_description: str, provider, model: str | None = None
) -> str:
    """Generate a skill name from the task description using LLM."""
    from common.llm.base import LLMRequest

    prompt_text = f"""Generate a skill name in slug format (lowercase with hyphens) for this task:
Task: {task_description}

Output ONLY the skill name, nothing else."""

    request = LLMRequest(
        prompt=prompt_text,
        model=model,
        temperature=0.3,
        max_tokens=50,
    )
    response = provider.complete(request)
    name = (response.content or "").strip().lower()

    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)
    name = "-".join(filter(None, name.split("-")))

    return name or "new-skill"


def revise_skill(
    feedback: str,
    name: str,
    description: str,
    when_to_use: str,
    body: str,
    provider,
    model: str | None = None,
) -> tuple[str, str, str, str]:
    """Revise skill based on user feedback."""
    from common.llm.base import LLMRequest

    prompt_text = f"""Revise the following skill based on user feedback.

Current skill:
- name: {name}
- description: {description}
- when_to_use: {when_to_use}
- body: {body}

User feedback: {feedback}

Output ONLY a JSON object with the revised skill:
```json
{{
  "name": "revised-name",
  "description": "revised description",
  "when_to_use": "revised when_to_use",
  "body": "revised body"
}}
```"""

    request = LLMRequest(
        prompt=prompt_text,
        model=model,
        temperature=0.3,
        max_tokens=1500,
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
        return (
            data.get("name", name),
            data.get("description", description),
            data.get("when_to_use", when_to_use),
            data.get("body", body),
        )
    except json.JSONDecodeError:
        logger.warning("revise_skill_parse_failed", content=content[:500])
        return name, description, when_to_use, body


def render_skill_draft(name: str, description: str, when_to_use: str, body: str) -> str:
    """Render a skill draft for display."""
    return f"""---
name: {name}
description: {description}
---

# {name} Skill

## When to use this skill
{when_to_use}

## Instructions
{body}
"""


def create_skill_from_description(
    task_description: str,
    skill_name: str | None = None,
) -> None:
    """Main entry point for creating a skill from a task description."""
    requires_common_config("skill", ["llm"])

    try:
        config = load_tool_config("skill")
        providers = discover_providers(config)
        provider_name = get_default_provider_name(config)
        provider = providers.get(provider_name)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not provider:
        click.echo(f"Error: provider '{provider_name}' not available.", err=True)
        sys.exit(1)

    from commands.setup import init_skill_agent_config

    agent_config = init_skill_agent_config()
    tools_description = load_tools_description(agent_config)
    existing_skills = load_existing_skills()

    click.echo(f"Task: {task_description}")
    click.echo("\nExtracting skill from description...")

    name, description, when_to_use, body = extract_skill_from_description(
        task_description,
        tools_description,
        existing_skills,
        provider,
        config=agent_config,
    )

    if skill_name:
        name = skill_name
    else:
        proposed_name = name
        click.echo(f"\nProposed skill name: {proposed_name}")
        if prompt_confirm("Use this name?"):
            name = proposed_name
        else:
            name = prompt_free_text("Enter skill name: ")
            while not name:
                name = prompt_free_text("Enter skill name: ")

    while True:
        draft = render_skill_draft(name, description, when_to_use, body)

        click.echo("\n" + "=" * 60)
        click.echo("DRAFT SKILL.MD")
        click.echo("=" * 60)
        click.echo(draft)
        click.echo("=" * 60)

        choice = prompt_with_options(
            "\n[R]evise / [A]ccept / [Q]uit: ",
            options=["r", "a", "q"],
            default="r",
        )

        if choice == "a":
            skill_path = get_skills_dir() / name

            if skill_path.exists():
                click.echo(
                    f"\nError: Skill '{name}' already exists at {skill_path}", err=True
                )
                if not prompt_confirm("Overwrite existing skill?"):
                    click.echo("Aborted.")
                    return

            skill_path.mkdir(parents=True, exist_ok=True)

            skill_content = f"""---
name: {name}
description: {description}
---

# {name} Skill

## When to use this skill
{when_to_use}

## Instructions
{body}
"""
            (skill_path / "SKILL.md").write_text(skill_content, encoding="utf-8")

            click.echo(f"\n✓ Created skill: {name}")
            click.echo(f"  Location: {skill_path}")
            return

        elif choice == "q":
            click.echo("Aborted.")
            return

        else:
            feedback = prompt_free_text("\nWhat would you like to change? ")
            if feedback:
                name, description, when_to_use, body = revise_skill(
                    feedback, name, description, when_to_use, body, provider
                )
