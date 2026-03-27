from __future__ import annotations

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import open_editor
from common.core.config import (
    get_tool_config_path,
    load_tool_config,
    save_tool_config,
)
from common.core.paths import get_skills_dir


DEFAULT_SKILL_AUTO_LEARN_PROMPT_TEMPLATE = """# Lessons Learned for {skill_name}

## What Works
- Skill execution `{skill_ref}` exited with code `{exit_code}`.
- Key stdout signal: `{stdout_preview}`

## What to Avoid
- Pattern leading to failure: `{stderr_preview}`

## Common Errors and Fixes
- Error: `{stderr_preview}` → Fix: adjust params/inputs and retry.
"""


def _get_skill_auto_learn_prompt_template() -> str:
    config = load_tool_config("skill")
    template = config.get("auto_learn_prompt")
    if isinstance(template, str) and template.strip():
        return template

    config["auto_learn_prompt"] = DEFAULT_SKILL_AUTO_LEARN_PROMPT_TEMPLATE
    save_tool_config("skill", config)
    return DEFAULT_SKILL_AUTO_LEARN_PROMPT_TEMPLATE


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("auto-learn")
    def auto_learn_group():
        """Manage skill auto-learn prompt template."""
        pass

    @auto_learn_group.command("path")
    def auto_learn_path():
        """Show config path for skill auto-learn prompt."""
        _get_skill_auto_learn_prompt_template()
        click.echo(get_tool_config_path("skill"))

    @auto_learn_group.command("show")
    def auto_learn_show():
        """Show current skill auto-learn prompt template."""
        click.echo(_get_skill_auto_learn_prompt_template())

    @auto_learn_group.command("edit")
    def auto_learn_edit():
        """Edit skill auto-learn prompt template."""
        _get_skill_auto_learn_prompt_template()
        path = get_tool_config_path("skill")
        if not path.exists():
            save_tool_config(
                "skill",
                {"auto_learn_prompt": DEFAULT_SKILL_AUTO_LEARN_PROMPT_TEMPLATE},
            )
        else:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if "auto_learn_prompt" not in data:
                data["auto_learn_prompt"] = DEFAULT_SKILL_AUTO_LEARN_PROMPT_TEMPLATE
                path.write_text(
                    yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
        open_editor(path)

    return CommandManifest(name="auto-learn", click_command=auto_learn_group)
