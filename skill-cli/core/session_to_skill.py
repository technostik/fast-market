from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from common import structlog
from common.agent.session import Session
from common.core.config import (
    ConfigError,
    load_common_config,
    load_tool_config,
    requires_common_config,
)
from common.core.paths import get_skills_dir
from common.learn import extract_skill_from_session
from common.llm.registry import discover_providers, get_default_provider_name

from core.repl import prompt_confirm, prompt_free_text, prompt_with_options

logger = structlog.get_logger(__name__)


def load_session(session_file: Path) -> Session:
    """Load a session from a YAML file."""
    data = yaml.safe_load(session_file.read_text(encoding="utf-8"))
    if not data:
        raise ValueError("Empty session file")
    return Session.from_dict(data)


def generate_skill_name(session: Session, provider, model: str | None = None) -> str:
    """Generate a skill name from the session task description using LLM."""
    from common.llm.base import LLMRequest

    prompt_text = f"""Generate a skill name in slug format (lowercase with hyphens) for this task:
Task: {session.task_description}

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
    body: str,
    provider,
    model: str | None = None,
) -> tuple[str, str, str]:
    """Revise skill based on user feedback."""
    from common.llm.base import LLMRequest

    prompt_text = f"""Revise the following skill based on user feedback.

Current skill:
- name: {name}
- description: {description}
- body: {body}

User feedback: {feedback}

Output ONLY a JSON object with the revised skill:
```json
{{
  "name": "revised-name",
  "description": "revised description",
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

    try:
        import json

        data = json.loads(content)
        return (
            data.get("name", name),
            data.get("description", description),
            data.get("body", body),
        )
    except json.JSONDecodeError:
        logger.warning("revise_skill_parse_failed", content=content[:500])
        return name, description, body


def render_skill_draft(name: str, description: str, body: str) -> str:
    """Render a skill draft for display."""
    return f"""---
name: {name}
description: {description}
---

# {name} Skill

## When to use this skill
{description}

## Instructions
{body}
"""


def create_skill_from_session(
    session_file: Path,
    skill_name: str | None = None,
) -> None:
    """Main entry point for creating a skill from a session."""
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

    click.echo(f"Loading session from: {session_file}")
    session = load_session(session_file)

    click.echo(f"Task: {session.task_description}")
    click.echo(f"Outcome: {'success' if session.exit_code == 0 else 'failed'}")

    if not skill_name:
        click.echo("\nGenerating skill name...")
        skill_name = generate_skill_name(session, provider)
        click.echo(f"Proposed skill name: {skill_name}")

        if not prompt_confirm("Use this name?"):
            skill_name = prompt_free_text("Enter skill name: ")
            while not skill_name:
                skill_name = prompt_free_text("Enter skill name: ")

    click.echo("\nExtracting skill from session...")
    name, description, body = extract_skill_from_session(session, provider)

    if skill_name:
        name = skill_name

    while True:
        draft = render_skill_draft(name, description, body)

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
{description}

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
                name, description, body = revise_skill(
                    feedback, name, description, body, provider
                )
