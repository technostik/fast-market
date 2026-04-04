from __future__ import annotations

import click
import yaml
from pathlib import Path

from commands.base import CommandManifest
from commands.params import SkillNameType, SessionFileType
from common.cli.helpers import open_editor
from common.core.config import (
    get_tool_config_path,
    load_tool_config,
    save_tool_config,
    requires_common_config,
    load_common_config,
    resolve_llm_config,
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
    analyze_session,
    update_learn_file,
)
from common.llm.registry import discover_providers, get_default_provider_name
from common.agent.session import Session
from core.skill import Skill


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

    @auto_learn_group.command("reset")
    @click.option(
        "--result",
        "-r",
        is_flag=True,
        help="Reset learn_result_template to default",
    )
    @click.option(
        "--compact",
        "-c",
        is_flag=True,
        help="Reset learn_compacting_prompt to default",
    )
    @click.option(
        "--all",
        "-a",
        is_flag=True,
        help="Reset all templates to defaults",
    )
    def auto_learn_reset(result, compact, all):
        """Reset auto-learn templates to defaults."""
        path = get_tool_config_path("skill")

        if not path.exists():
            click.echo("No config file found, nothing to reset.")
            return

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        keys_to_reset = []

        if all:
            keys_to_reset = [
                "learn_analysis_prompt",
                "learn_result_template",
                "learn_compacting_prompt",
            ]
        elif compact:
            keys_to_reset = ["learn_compacting_prompt"]
        elif result:
            keys_to_reset = ["learn_result_template"]
        else:
            keys_to_reset = ["learn_analysis_prompt"]

        for key in keys_to_reset:
            if key in data:
                del data[key]

        if data:
            path.write_text(dump_yaml(data, sort_keys=False), encoding="utf-8")
        else:
            path.unlink()

        click.echo(f"Reset: {', '.join(keys_to_reset)}")

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
            config = resolve_llm_config("skill")
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
            temperature=config.get("default_temperature"),
        )

        learn_path.write_text(compacted + "\n", encoding="utf-8")
        click.echo(f"LEARN.md compacted: {len(compacted.splitlines())} lines")

    @auto_learn_group.command("from")
    @click.argument("session_file", type=SessionFileType())
    @click.argument("skill_name", type=SkillNameType())
    @click.option(
        "--workdir",
        "-w",
        default=None,
        type=click.Path(),
        help="Working directory for session files (default: common config workdir)",
    )
    @click.option(
        "--debug",
        "-d",
        is_flag=True,
        default=False,
        help="Enable debug output",
    )
    def auto_learn_from(session_file, skill_name, workdir, debug):
        """Learn from a session YAML file to update skill's LEARN.md."""
        if debug:
            click.echo(
                f"[DEBUG] session_file argument: {session_file} (type: {type(session_file)})"
            )
            click.echo(f"[DEBUG] skill_name: {skill_name}")
            click.echo(f"[DEBUG] workdir: {workdir}")
        requires_common_config("skill", ["llm"])

        session_path = get_skills_dir() / skill_name
        if not session_path.exists():
            click.echo(f"Error: Skill '{skill_name}' not found", err=True)
            return

        skill = Skill.from_path(session_path)
        learn_path = skill.path / "LEARN.md"

        if workdir is None:
            common_config = load_common_config()
            workdir = common_config.get("workdir") or "."

        base_dir = Path(workdir).expanduser().resolve()
        session_file_input = Path(session_file)
        session_file_path = None

        if session_file_input.is_absolute() and session_file_input.exists():
            session_file_path = session_file_input
        elif (base_dir / session_file_input).exists():
            session_file_path = base_dir / session_file_input

        if session_file_path is None:
            click.echo(f"Error: Session file not found: {session_file}", err=True)
            return

        if session_file_path.is_dir():
            candidates = list(session_file_path.glob("*.yaml")) + list(
                session_file_path.glob("*.session.yaml")
            )
            if not candidates:
                click.echo(
                    f"Error: No session files found in directory: {session_file}",
                    err=True,
                )
                return
            session_file_path = candidates[0]

        if not session_file_path.exists() or not session_file_path.is_file():
            click.echo(f"Error: Session file not found: {session_file}", err=True)
            return

        try:
            session_data = yaml.safe_load(session_file_path.read_text(encoding="utf-8"))
            if not session_data:
                click.echo("Error: Session file is empty", err=True)
                return
            if debug:
                click.echo(f"[DEBUG] session_data type: {type(session_data)}")
                click.echo(
                    f"[DEBUG] session_data keys: {session_data.keys() if isinstance(session_data, dict) else 'N/A'}"
                )
            session = Session.from_dict(session_data)
            if debug:
                click.echo(
                    f"[DEBUG] Session.from_dict succeeded, session type: {type(session)}"
                )
        except Exception as e:
            click.echo(f"Error: Failed to load session file: {e}", err=True)
            if debug:
                import traceback

                click.echo(f"[DEBUG] Traceback: {traceback.format_exc()}")
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

        try:
            config = resolve_llm_config("skill")
            learn_analysis_prompt = get_learn_analysis_prompt(config)
            learn_result_template = get_learn_result_template(config)

            existing_learn_content = None
            if learn_path.exists():
                existing_learn_content = learn_path.read_text(encoding="utf-8")

            if debug:
                click.echo(f"[DEBUG] Calling analyze_session with:")
                click.echo(f"[DEBUG]   session type: {type(session)}")
                click.echo(f"[DEBUG]   skill.name: {skill.name}")
                click.echo(f"[DEBUG]   provider: {provider}")

            content, prompt = analyze_session(
                session,
                skill.name,
                provider,
                None,
                learn_analysis_prompt=learn_analysis_prompt,
                learn_result_template=learn_result_template,
                existing_learn_content=existing_learn_content,
                temperature=config.get("default_temperature"),
            )

            if debug:
                click.echo(
                    f"[DEBUG] analyze_session returned content (len={len(content) if content else 0})"
                )

            update_learn_file(
                skill.name,
                content,
                merge=True,
                provider=provider,
                model=None,
                temperature=config.get("default_temperature"),
            )

            if debug:
                click.echo(f"[DEBUG] update_learn_file completed")

            session_file_data = (
                yaml.safe_load(session_file_path.read_text(encoding="utf-8")) or {}
            )
            session_file_data["learning"] = {
                "prompt": prompt,
                "result": content,
            }
            if debug:
                click.echo(f"[DEBUG] Writing to session_file_path: {session_file_path}")
            session_file_path.write_text(
                dump_yaml(session_file_data, sort_keys=False),
                encoding="utf-8",
            )

            click.echo(f"Successfully updated LEARN.md for skill '{skill.name}'")
        except Exception as e:
            click.echo(f"Error: Auto-learn failed: {e}", err=True)
            if debug:
                import traceback

                click.echo(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return

    return CommandManifest(name="auto-learn", click_command=auto_learn_group)
