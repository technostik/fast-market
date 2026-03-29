from __future__ import annotations

import click
import yaml

from commands.base import CommandManifest
from commands.params import SkillNameType
from common.cli.helpers import open_editor
from common.core.config import (
    get_tool_config_path,
    load_tool_config,
    save_tool_config,
    requires_common_config,
)
from common.core.paths import get_skills_dir
from common.core.yaml_utils import dump_yaml
from common.learn import (
    LEARN_ANALYSIS_PROMPT_TEMPLATE,
    LEARN_RESULT_TEMPLATE,
    LEARN_COMPACTING_PROMPT_TEMPLATE,
    get_learn_analysis_prompt,
    get_learn_result_template,
    get_learn_compacting_prompt,
    compress_learn_content,
    MAX_LEARN_LINES,
)
from common.llm.registry import discover_providers, get_default_provider_name


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("auto-learn")
    def auto_learn_group():
        """Manage skill auto-learn templates."""
        pass

    @auto_learn_group.command("path")
    def auto_learn_path():
        """Show config path for auto-learn templates."""
        get_learn_analysis_prompt()
        click.echo(get_tool_config_path("skill"))

    @auto_learn_group.command("show")
    @click.option(
        "--result",
        "-r",
        is_flag=True,
        help="Show learn_result_template instead of learn_analysis_prompt",
    )
    @click.option(
        "--compact",
        "-c",
        is_flag=True,
        help="Show learn_compacting_prompt",
    )
    def auto_learn_show(result, compact):
        """Show current auto-learn template."""
        if compact:
            click.echo(get_learn_compacting_prompt())
        elif result:
            click.echo(get_learn_result_template())
        else:
            click.echo(get_learn_analysis_prompt())

    @auto_learn_group.command("edit")
    @click.option(
        "--result",
        "-r",
        is_flag=True,
        help="Edit learn_result_template instead of learn_analysis_prompt",
    )
    @click.option(
        "--compact",
        "-c",
        is_flag=True,
        help="Edit learn_compacting_prompt",
    )
    def auto_learn_edit(result, compact):
        """Edit auto-learn templates."""
        if compact:
            config_key = "learn_compacting_prompt"
            default_template = LEARN_COMPACTING_PROMPT_TEMPLATE
        elif result:
            config_key = "learn_result_template"
            default_template = LEARN_RESULT_TEMPLATE
        else:
            config_key = "learn_analysis_prompt"
            default_template = LEARN_ANALYSIS_PROMPT_TEMPLATE

        path = get_tool_config_path("skill")
        if not path.exists():
            data = {config_key: default_template}
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if config_key not in data:
                data[config_key] = default_template
        path.write_text(
            dump_yaml(data),
            encoding="utf-8",
        )
        open_editor(path)

    @auto_learn_group.command("compact")
    @click.argument("skill_name", type=SkillNameType())
    @click.option(
        "--lines",
        "-n",
        type=int,
        default=MAX_LEARN_LINES,
        help=f"Target number of lines (default: {MAX_LEARN_LINES})",
    )
    def auto_learn_compact(skill_name, lines):
        """Compact LEARN.md for a skill using LLM."""
        requires_common_config("skill", ["llm"])

        skill_path = get_skills_dir() / skill_name
        learn_path = skill_path / "LEARN.md"

        if not learn_path.exists():
            click.echo(f"Error: LEARN.md not found for skill '{skill_name}'", err=True)
            return

        existing_content = learn_path.read_text(encoding="utf-8")
        line_count = len(existing_content.splitlines())
        if line_count <= lines:
            click.echo(
                f"LEARN.md has {line_count} lines, no compaction needed (target: {lines})"
            )
            return

        try:
            config = load_tool_config("skill")
            providers = discover_providers(config)
            provider_name = get_default_provider_name(config)
            provider = providers.get(provider_name)
        except Exception as e:
            click.echo(f"Error: Failed to load LLM provider: {e}", err=True)
            return

        if not provider:
            click.echo(f"Error: No LLM provider available", err=True)
            return

        click.echo(f"Compacting LEARN.md ({line_count} lines -> {lines} lines)...")

        learn_result_template = get_learn_result_template(
            config.get("learn_result_template")
        )

        compacted = compress_learn_content(
            content=existing_content,
            provider=provider,
            use_compacting=True,
            learn_result_template=learn_result_template,
            max_lines=lines,
        )

        learn_path.write_text(compacted + "\n", encoding="utf-8")
        click.echo(f"LEARN.md compacted: {len(compacted.splitlines())} lines")

    return CommandManifest(name="auto-learn", click_command=auto_learn_group)
