from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.config import ConfigError, load_tool_config, requires_common_config
from common.core.paths import get_skills_dir
from common.llm.registry import discover_providers, get_default_provider_name
from common.skill.skill import Skill, discover_skills


class SkillRefType(click.ParamType):
    name = "SKILL_REF"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem

        try:
            skills_dir = get_skills_dir()
            skills = discover_skills(skills_dir)
        except Exception:
            return []

        items = []
        for skill in skills:
            if skill.name.startswith(incomplete):
                items.append(CompletionItem(skill.name, help=skill.description or ""))

            if "/" in incomplete and incomplete.startswith(skill.name + "/"):
                script_prefix = incomplete[len(skill.name) + 1 :]
                if skill.has_scripts:
                    scripts_dir = skill.path / "scripts"
                    if not scripts_dir.exists():
                        continue
                    for script in sorted(scripts_dir.iterdir()):
                        if script.is_file() and not script.name.startswith("."):
                            if script.name.startswith(script_prefix):
                                items.append(
                                    CompletionItem(
                                        f"{skill.name}/{script.name}",
                                        help=f"Script in {skill.name}",
                                    )
                                )
        return items

    def convert(self, value, param, ctx):
        return value


class SkillParamType(click.ParamType):
    name = "KEY=VALUE"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem

        skill_ref = ctx.params.get("skill_ref", "")
        if not skill_ref:
            return []

        try:
            skill_name = str(skill_ref).split("/", 1)[0]
            skill_path = get_skills_dir() / skill_name
            skill = Skill.from_path(skill_path)
        except Exception:
            return []

        if not skill or not skill.parameters:
            return []

        already = set()
        for val in (ctx.params.get("params") or []):
            if "=" in val:
                already.add(val.split("=")[0])

        required_items = []
        optional_items = []
        for p in skill.parameters:
            name = p.get("name")
            if not name or name in already:
                continue
            key = f"{name}="
            if not key.startswith(incomplete):
                continue
            desc = p.get("description", "")
            if p.get("required", False):
                desc = f"[required] {desc}".strip()
                required_items.append(CompletionItem(key, help=desc))
            else:
                optional_items.append(CompletionItem(key, help=desc))

        return required_items + optional_items

    def convert(self, value, param, ctx):
        return value


def _resolve_prompt_provider_model(
    provider: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    try:
        llm_cfg = load_tool_config("apply")
    except Exception:
        llm_cfg = {}

    provider_name = provider
    if not provider_name:
        try:
            provider_name = get_default_provider_name(llm_cfg)
        except Exception:
            provider_name = None

    model_name = model
    if not model_name and provider_name:
        providers_cfg = llm_cfg.get("providers")
        if not isinstance(providers_cfg, dict):
            providers_cfg = llm_cfg.get("llm", {}).get("providers", {})
        provider_settings = providers_cfg.get(provider_name, {})
        if isinstance(provider_settings, dict):
            default_model = provider_settings.get("default_model")
            if default_model:
                model_name = str(default_model)

    return provider_name, model_name


def _apply_skill_impl(
    skill_ref: str,
    params: tuple[str, ...],
    workdir: str = ".",
    timeout: int = 60,
    dry_run: bool = False,
    fmt: str = "text",
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Core logic of skill apply, callable from both apply and run commands."""
    from common.skill.runner import (
        execute_skill_prompt,
        execute_skill_run,
        execute_skill_script,
        resolve_skill_script,
    )

    workdir_path = Path(workdir).expanduser().resolve()

    provided_params: dict[str, str] = {}
    invalid_params: list[str] = []
    for param in params:
        if "=" not in param:
            invalid_params.append(param)
            continue
        key, value = param.split("=", 1)
        provided_params[key] = value

    if invalid_params:
        click.echo(
            f"Error: invalid parameter(s), expected KEY=VALUE: {', '.join(invalid_params)}",
            err=True,
        )
        sys.exit(1)

    skill_name = skill_ref.split("/", 1)[0]
    skill_path = get_skills_dir() / skill_name
    skill = Skill.from_path(skill_path)
    if not skill:
        click.echo(f"Skill '{skill_name}' not found", err=True)
        sys.exit(1)

    for p in skill.parameters:
        if p.get("required") and p["name"] not in provided_params and "default" not in p:
            click.echo(
                f"Error: required parameter '{p['name']}' not provided",
                err=True,
            )
            click.echo(f"  Description: {p.get('description', '')}", err=True)
            sys.exit(1)

    defaults_applied: set[str] = set()
    for p in skill.parameters:
        if p["name"] not in provided_params and "default" in p:
            provided_params[p["name"]] = str(p["default"])
            defaults_applied.add(p["name"])

    resolved_skill, script_path = resolve_skill_script(skill_ref)
    if not resolved_skill:
        click.echo(f"Skill '{skill_name}' not found", err=True)
        sys.exit(1)

    if dry_run and fmt != "json":
        click.echo(f"[DRY RUN] Skill: {resolved_skill.name}")
        click.echo(f"[DRY RUN] Workdir: {workdir_path}")
        click.echo("[DRY RUN] Parameters:")
        for key in sorted(provided_params):
            suffix = " (default)" if key in defaults_applied else ""
            click.echo(f"  {key} = {provided_params[key]}{suffix}")
        click.echo("[DRY RUN] Environment variables that would be set:")
        for key in sorted(provided_params):
            click.echo(f"  SKILL_{key.upper()}={provided_params[key]}")

    if skill.has_scripts:
        if dry_run:
            if fmt == "json":
                click.echo(json.dumps({"exit_code": 0, "stdout": "", "stderr": ""}))
                return
            click.echo("[DRY RUN] Mode: script")
            click.echo(f"[DRY RUN] Script: {script_path if script_path else '(unresolved)'}")
            return

        result = execute_skill_script(
            skill_ref=skill_ref,
            workdir=workdir_path,
            params=provided_params or None,
            timeout=timeout,
        )
    elif skill.run:
        if dry_run:
            cmd_preview = skill.run
            for key, value in provided_params.items():
                cmd_preview = cmd_preview.replace(f"{{{key}}}", value)
            if fmt == "json":
                click.echo(json.dumps({"exit_code": 0, "stdout": "", "stderr": ""}))
                return
            click.echo("[DRY RUN] Mode: run: (inline command)")
            click.echo(f"[DRY RUN] Command: {cmd_preview}")
            return

        result = execute_skill_run(
            skill=skill,
            workdir=workdir_path,
            params=provided_params or None,
            timeout=timeout,
        )
    else:
        body = skill.get_body()
        if not body:
            click.echo(
                f"Error: Skill '{skill.name}' has no scripts/, no run: command, and no body content.",
                err=True,
            )
            sys.exit(1)

        provider_name, model_name = _resolve_prompt_provider_model(provider, model)

        if dry_run:
            if fmt == "json":
                click.echo(json.dumps({"exit_code": 0, "stdout": "", "stderr": ""}))
                return
            click.echo("[DRY RUN] Mode: prompt (via task apply)")
            if provider_name:
                click.echo(f"[DRY RUN] Provider: {provider_name}")
            if model_name:
                click.echo(f"[DRY RUN] Model: {model_name}")
            click.echo("[DRY RUN] Task description:")
            preview = body[:200] + ("..." if len(body) > 200 else "")
            click.echo(f"  {preview}")
            return

        result = execute_skill_prompt(
            skill=skill,
            workdir=workdir_path,
            params=provided_params or None,
            timeout=timeout,
            provider=provider_name,
            model=model_name,
        )

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        )
        return

    if result.stdout:
        click.echo(result.stdout, nl=False)
    if result.stderr:
        click.echo(result.stderr, nl=False, err=True)
    sys.exit(result.exit_code)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group()
    def skill_group():
        """Manage skills for agentic task execution."""
        pass

    @skill_group.command("list")
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    def list_skills(fmt):
        """List all available skills."""
        skills_dir = get_skills_dir()
        skills = discover_skills(skills_dir)

        if fmt == "json":
            click.echo(
                json.dumps(
                    [
                        {
                            "name": s.name,
                            "description": s.description,
                            "has_scripts": s.has_scripts,
                        }
                        for s in skills
                    ],
                    indent=2,
                )
            )
            return

        if not skills:
            click.echo(f"No skills found in {skills_dir}")
            return

        click.echo(f"Skills directory: {skills_dir}\n")
        for skill in skills:
            click.echo(f"  {skill.name}")
            if skill.description:
                click.echo(f"    Description: {skill.description}")
            if skill.has_scripts:
                click.echo("    Has executable scripts")

    @skill_group.command("path")
    def show_path():
        """Show the skills directory path."""
        click.echo(get_skills_dir())

    @skill_group.command("create")
    @click.argument("name")
    @click.option("--description", "-d", help="Skill description")
    @click.option("--with-scripts", "-s", is_flag=True, help="Create scripts directory")
    def create_skill(name, description, with_scripts):
        """Create a new skill scaffold."""
        skills_dir = get_skills_dir()
        skill_path = skills_dir / name

        if skill_path.exists():
            click.echo(f"Error: Skill '{name}' already exists", err=True)
            sys.exit(1)

        skill_path.mkdir(parents=True, exist_ok=True)

        template = f"""---
name: {name}
description: {description or "No description provided"}
---

# {name} Skill

## When to use this skill
Describe when this skill should be used.

## Instructions
Provide step-by-step instructions for using this skill.

## Examples
Include examples of how to use this skill.
"""
        (skill_path / "SKILL.md").write_text(template, encoding="utf-8")

        if with_scripts:
            (skill_path / "scripts").mkdir()
            (skill_path / "scripts" / "README.md").write_text(
                "# Scripts Directory\n\nPlace executable scripts here.\n"
            )

        click.echo(f"Created skill: {name} at {skill_path}")

    @skill_group.command("show")
    @click.argument("name")
    def show_skill(name):
        """Show skill details."""
        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            sys.exit(1)

        skill = Skill.from_path(skill_path)
        if not skill:
            click.echo(f"Error: '{name}' is not a valid skill", err=True)
            sys.exit(1)

        click.echo(f"  {skill.name}")
        click.echo(f"    Path: {skill.path}")
        if skill.description:
            click.echo(f"    Description: {skill.description}")

        click.echo("\n  --- SKILL.md ---")
        content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        click.echo(content[:500] + ("..." if len(content) > 500 else ""))

        if skill.has_scripts:
            click.echo("\n  Scripts:")
            for script in (skill_path / "scripts").iterdir():
                if script.is_file() and not script.name.startswith("."):
                    click.echo(f"    - {script.name}")

    @skill_group.command("delete")
    @click.argument("name")
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation")
    def delete_skill(name, force):
        """Delete a skill."""
        skill_path = get_skills_dir() / name
        if not skill_path.exists():
            click.echo(f"Error: Skill '{name}' not found", err=True)
            sys.exit(1)

        if not force:
            click.confirm(f"Delete skill '{name}'?", abort=True)

        import shutil

        shutil.rmtree(skill_path)
        click.echo(f"Deleted skill: {name}")

    @skill_group.command("apply")
    @click.argument("skill_ref", type=SkillRefType())
    @click.argument("params", nargs=-1, type=SkillParamType())
    @click.option(
        "--workdir",
        "-w",
        default=".",
        type=click.Path(),
        help="Working directory (default: current dir)",
    )
    @click.option(
        "--timeout",
        "-t",
        type=int,
        default=60,
        help="Execution timeout in seconds",
    )
    @click.option(
        "--dry-run",
        "-n",
        is_flag=True,
        help="Show what would be executed without running",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format",
    )
    @click.option(
        "--provider",
        "-P",
        default=None,
        help="LLM provider (for prompt mode skills)",
    )
    @click.option(
        "--model",
        "-m",
        default=None,
        help="LLM model (for prompt mode skills)",
    )
    def apply_skill(skill_ref, params, workdir, timeout, dry_run, fmt, provider, model):
        """Apply (execute) a skill by name.

        SKILL_REF is the skill name or 'skillname/scriptname'.
        PARAMS are KEY=VALUE pairs passed as SKILL_KEY environment variables.
        """
        _apply_skill_impl(
            skill_ref=skill_ref,
            params=params,
            workdir=workdir,
            timeout=timeout,
            dry_run=dry_run,
            fmt=fmt,
            provider=provider,
            model=model,
        )

    @skill_group.command("run")
    @click.argument("task")
    @click.option(
        "--provider",
        "-P",
        default=None,
        help="LLM provider for routing and execution",
    )
    @click.option(
        "--model",
        "-m",
        default=None,
        help="LLM model for routing",
    )
    @click.option(
        "--threshold",
        "-t",
        type=float,
        default=0.5,
        help="Minimum confidence score to accept a match (default: 0.5)",
    )
    @click.option(
        "--dry-run",
        "-n",
        is_flag=True,
        help="Show matched skill and params without executing",
    )
    @click.option(
        "--workdir",
        "-w",
        default=".",
        type=click.Path(),
        help="Working directory for execution",
    )
    def run_skill(task, provider, model, threshold, dry_run, workdir):
        """Auto-discover and run the best skill for a task description."""
        from common.skill.router import route

        requires_common_config("skill", ["llm"])
        try:
            config = load_tool_config("skill")
            providers = discover_providers(config)
            provider_name = provider or get_default_provider_name(config)
            llm = providers.get(provider_name)
        except ConfigError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        if not llm:
            click.echo(f"Error: provider '{provider_name}' not available.", err=True)
            sys.exit(1)

        click.echo(f"Routing: '{task}'...", err=True)

        match = route(
            task,
            provider=llm,
            model=model,
            confidence_threshold=threshold,
        )

        if match.skill is None:
            click.echo(
                f"No matching skill found (confidence: {match.confidence:.2f})",
                err=True,
            )
            click.echo(f"Reason: {match.reason}", err=True)
            click.echo("\nAvailable skills:", err=True)
            for s in discover_skills(get_skills_dir()):
                click.echo(f"  {s.name} — {s.description}", err=True)
            sys.exit(1)

        click.echo(
            f"Matched: '{match.skill.name}' "
            f"(confidence: {match.confidence:.0%}, {match.reason})",
            err=True,
        )

        if match.params:
            click.echo(f"Extracted params: {match.params}", err=True)

        params_args = tuple(f"{k}={v}" for k, v in match.params.items())

        if dry_run:
            click.echo(
                f"\n[DRY RUN] Would execute: skill apply {match.skill.name}",
                err=True,
            )
            for k, v in match.params.items():
                click.echo(f"  {k}={v}", err=True)
            return

        _apply_skill_impl(
            skill_ref=match.skill.name,
            params=params_args,
            workdir=workdir,
            timeout=300,
            dry_run=False,
            fmt="text",
            provider=provider_name,
            model=model,
        )

    return CommandManifest(name="skill", click_command=skill_group)


def register_completion(cli_group):
    """Register the 'completion' command on the top-level CLI group."""

    @cli_group.command("completion")
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
