from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import open_editor
from common.core.config import (
    ConfigError,
    get_tool_config_path,
    load_tool_config,
    requires_common_config,
    save_tool_config,
)
from common.core.paths import get_skills_dir
from common.llm.registry import discover_providers, get_default_provider_name
from common.skill.skill import Skill, discover_skills


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


class SkillNameType(click.ParamType):
    name = "SKILL_NAME"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem

        try:
            skills = discover_skills(get_skills_dir())
        except Exception:
            return []

        return [
            CompletionItem(skill.name, help=skill.description or "")
            for skill in skills
            if skill.name.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


class SkillFileType(click.ParamType):
    name = "FILE"

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem

        skill_name = ctx.params.get("skill_name", "")
        if not skill_name:
            return []

        try:
            skill_dir = (get_skills_dir() / str(skill_name)).resolve()
        except Exception:
            return []

        if not skill_dir.exists() or not skill_dir.is_dir():
            return []

        items = []
        for path in sorted(skill_dir.rglob("*")):
            if path.name.startswith(".") or path.is_dir():
                continue
            try:
                rel = path.relative_to(skill_dir).as_posix()
            except Exception:
                continue
            if rel.startswith(incomplete):
                items.append(CompletionItem(rel))
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


def _write_local_session_file(
    save_session: str | None,
    skill_ref: str,
    result,
    provided_params: dict[str, str],
) -> None:
    """Persist a minimal session artifact for non-prompt skill executions."""
    if not save_session:
        return

    session_path = Path(save_session).expanduser().resolve()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "metrics": {
            "total_tool_calls": 1,
            "error_count": 0 if result.exit_code == 0 else 1,
            "guess_count": 0,
            "success_rate": 1.0 if result.exit_code == 0 else 0.0,
            "iterations_used": 1,
        },
        "turns": [
            {
                "role": "assistant",
                "content": (
                    f"Skill execution summary: skill_ref={skill_ref}, "
                    f"exit_code={result.exit_code}, params={provided_params}"
                ),
                "tool_calls": [
                    {
                        "arguments": {
                            "command": f"skill apply {skill_ref}",
                            "params": provided_params,
                        },
                        "stdout": result.stdout or "",
                        "stderr": result.stderr or "",
                        "exit_code": result.exit_code,
                    }
                ],
            }
        ]
    }
    session_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _apply_skill_impl(
    skill_ref: str,
    params: tuple[str, ...],
    workdir: str = ".",
    timeout: int = 60,
    dry_run: bool = False,
    fmt: str = "text",
    provider: str | None = None,
    model: str | None = None,
    auto_learn: bool = False,
    save_session: str | None = None,
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
        _write_local_session_file(save_session, skill_ref, result, provided_params)
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
        _write_local_session_file(save_session, skill_ref, result, provided_params)
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
            save_session=Path(save_session).expanduser().resolve() if save_session else None,
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

    if auto_learn and not dry_run:
        try:
            skill_name = skill_ref.split("/", 1)[0]
            learn_path = get_skills_dir() / skill_name / "LEARN.md"
            learn_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_preview = (result.stdout or "").strip().splitlines()
            stderr_preview = (result.stderr or "").strip().splitlines()
            stdout_line = stdout_preview[0] if stdout_preview else "no stdout"
            stderr_line = stderr_preview[0] if stderr_preview else "no stderr"
            template = _get_skill_auto_learn_prompt_template()
            learn_md = template.format(
                skill_name=skill_name,
                skill_ref=skill_ref,
                exit_code=result.exit_code,
                stdout_preview=stdout_line,
                stderr_preview=stderr_line,
                timestamp=datetime.utcnow().isoformat(),
            )
            if learn_path.exists():
                existing = learn_path.read_text(encoding="utf-8").rstrip()
                merged = (
                    f"{existing}\n\n---\n"
                    f"<!-- run: {datetime.utcnow().isoformat()} -->\n\n"
                    f"{learn_md}\n"
                )
                learn_path.write_text(merged, encoding="utf-8")
            else:
                learn_path.write_text(learn_md + "\n", encoding="utf-8")
            click.echo(f"[AUTO-LEARN] LEARN.md updated: {learn_path}", err=True)
        except Exception as exc:
            click.echo(f"[AUTO-LEARN] Failed: {exc}", err=True)

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

    @skill_group.command("edit")
    @click.argument("skill_name", type=SkillNameType())
    @click.argument("file", required=False, default=None, type=SkillFileType())
    @click.option(
        "--create",
        "-c",
        is_flag=True,
        help="Create FILE if it does not exist",
    )
    def edit_skill(skill_name, file, create):
        """Edit a skill file in the default editor."""
        skills_dir = get_skills_dir()
        skill_dir = skills_dir / skill_name

        if not skill_dir.exists():
            click.echo(f"Error: Skill '{skill_name}' not found", err=True)
            sys.exit(1)

        if file is None:
            target = skill_dir / "SKILL.md"
        else:
            target = skill_dir / file

        skill_dir_resolved = skill_dir.resolve()
        target_resolved = target.resolve()
        if not str(target_resolved).startswith(str(skill_dir_resolved)):
            click.echo("Error: path must be within skill directory", err=True)
            sys.exit(1)

        if not target_resolved.exists():
            if not create:
                click.echo(
                    f"Error: '{file}' not found in skill '{skill_name}'.\n"
                    "Hint: use --create to create it",
                    err=True,
                )
                sys.exit(1)

            target_resolved.parent.mkdir(parents=True, exist_ok=True)
            if target_resolved.suffix == ".sh":
                target_resolved.write_text(
                    "#!/usr/bin/env bash\nset -euo pipefail\n\n",
                    encoding="utf-8",
                )
                target_resolved.chmod(target_resolved.stat().st_mode | 0o111)
            else:
                target_resolved.touch()
            click.echo(f"Created: {target_resolved}")

        open_editor(target_resolved)

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
    @click.option(
        "--save-session",
        default=None,
        type=click.Path(),
        help="Save task session to this file (forwarded to task apply)",
    )
    @click.option(
        "--auto-learn",
        "-L",
        is_flag=True,
        help="After execution, update LEARN.md for this skill",
    )
    def apply_skill(
        skill_ref,
        params,
        workdir,
        timeout,
        dry_run,
        fmt,
        provider,
        model,
        save_session,
        auto_learn,
    ):
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
            auto_learn=auto_learn,
            save_session=save_session,
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
        "--workdir",
        "-w",
        default=".",
        type=click.Path(),
        help="Working directory for execution",
    )
    @click.option(
        "--max-iterations",
        "-i",
        type=int,
        default=10,
        help="Max number of skill executions",
    )
    @click.option(
        "--verbose",
        "-v",
        is_flag=True,
        help="Print each skill attempt and distilled result",
    )
    @click.option(
        "--retry-limit",
        type=int,
        default=2,
        help="Max retries per failed skill",
    )
    def run_skill(task, provider, model, workdir, max_iterations, verbose, retry_limit):
        """Orchestrate multiple skills to accomplish a complex task."""
        from common.skill.router import run_router

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

        click.echo(f"Router started: '{task}'", err=True)

        state = run_router(
            goal=task,
            provider=llm,
            model=model,
            workdir=workdir,
            max_iterations=max_iterations,
            skill_timeout=300,
            retry_limit=retry_limit,
            verbose=verbose,
        )
        click.echo("\n" + "=" * 50, err=True)
        if state.done:
            click.echo(f"✓ Done: {state.final_result}", err=True)
            return
        if state.failed:
            click.echo(f"✗ Failed: {state.failure_reason}", err=True)
            sys.exit(1)
        click.echo(
            f"✗ Max iterations ({max_iterations}) reached without completion",
            err=True,
        )
        sys.exit(1)

    @skill_group.group("auto-learn")
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
