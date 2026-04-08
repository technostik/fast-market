from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.params import RunPlanFileType
from common.cli.helpers import get_editor, open_editor
from common.core.config import load_common_config
from core.repl import prompt_with_options, prompt_free_text, prompt_confirm


def find_run_yaml_files(search_dir: Path, recursive: bool = True) -> list[Path]:
    """Find all run.yaml and run.yml files in directory and subdirectories."""
    run_files = []

    if recursive:
        for pattern in ["run.yaml", "run.yml"]:
            run_files.extend(search_dir.rglob(pattern))
    else:
        for pattern in ["run.yaml", "run.yml"]:
            run_files.extend(search_dir.glob(pattern))

    return sorted(set(run_files))


def load_plan(path: Path) -> dict:
    """Load a run.yaml plan file."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Invalid plan YAML format: {path}")
    if "plan" not in data:
        data["plan"] = []
    return data


def save_plan(path: Path, data: dict) -> None:
    """Save a run.yaml plan file."""
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True))


def format_step(step: dict, index: int) -> str:
    """Format a step for display."""
    action = step.get("action", "unknown")
    lines = [f"  [{index}] {action.upper()}"]

    if action == "run":
        skill = step.get("skill", "?")
        lines.append(f"      Skill: {skill}")
        params = step.get("params", {})
        if params:
            for k, v in params.items():
                lines.append(f"      {k}: {v}")
        if step.get("inject"):
            lines.append(f"      Inject: {step['inject'][:60]}...")
    elif action == "task":
        task_name = step.get("name", "").strip()
        if task_name:
            lines.append(f"      Auto-skill: auto-{task_name}")
        desc = step.get("description", "")
        lines.append(f"      {desc[:80]}{'...' if len(desc) > 80 else ''}")
        if step.get("instructions"):
            lines.append(f"      Instructions: {step['instructions'][:60]}...")
    elif action == "ask":
        question = step.get("question", "")
        lines.append(f"      {question[:80]}{'...' if len(question) > 80 else ''}")

    if step.get("context_hint"):
        lines.append(f"      Context: {step['context_hint'][:60]}...")

    return "\n".join(lines)


def show_step_detail(step: dict, index: int) -> None:
    """Show detailed view of a step."""
    action = step.get('action', 'unknown').upper()
    click.echo(f"\n{'=' * 60}")
    click.echo(f"Step {index}: {action}")
    click.echo(f"{'=' * 60}")

    # Show auto-skill name if this is a named task
    task_name = step.get("name", "").strip()
    if step.get("action") == "task" and task_name:
        click.echo(f"  Auto-skill: auto-{task_name}")

    for key, value in step.items():
        if key != "step":
            click.echo(f"  {key}: {value}")
    click.echo()


def _extract_placeholders(data: dict) -> dict:
    """Extract all {{key}} and {{key:default}} placeholders from a plan dict."""
    found = {}

    def _scan(obj):
        if isinstance(obj, str):
            for m in re.finditer(r"\{\{([^}]+)\}\}", obj):
                inner = m.group(1)
                if ":" in inner:
                    key, default = inner.split(":", 1)
                    key = key.strip()
                    found.setdefault(key, {"required": False, "default": default})
                else:
                    key = inner.strip()
                    if key not in found:
                        found[key] = {"required": True, "default": None}
        elif isinstance(obj, dict):
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)

    _scan(data)
    return found


def edit_step_in_editor(step: dict) -> dict | None:
    """Open step in editor and return modified step, or None if user cancels."""
    import subprocess
    import os

    editor = get_editor()

    # Create a temp file the editor can write to (more reliable than NamedTemporaryFile)
    fd, temp_path_str = tempfile.mkstemp(suffix=".yaml", prefix="run_plan_")
    temp_path = Path(temp_path_str)
    try:
        os.write(fd, yaml.dump(step, default_flow_style=False, sort_keys=False, allow_unicode=True).encode("utf-8"))
        os.close(fd)
    except Exception:
        os.close(fd)
        temp_path.unlink(missing_ok=True)
        click.echo("Error creating temp file for editor.", err=True)
        return None

    # Save original content for comparison
    original_content = temp_path.read_text(encoding="utf-8")

    # Open the editor
    try:
        import shlex
        cmd_parts = shlex.split(editor) + [str(temp_path)]
        result = subprocess.run(cmd_parts)
    except FileNotFoundError:
        click.echo(f"Editor '{editor}' not found.", err=True)
        temp_path.unlink(missing_ok=True)
        return None

    try:
        if not temp_path.exists():
            click.echo("Error: editor deleted the file.", err=True)
            return None

        new_content = temp_path.read_text(encoding="utf-8")

        # If nothing changed, return the original step
        if new_content.strip() == original_content.strip():
            return step

        modified = yaml.safe_load(new_content)
        if not isinstance(modified, dict):
            click.echo("Error: edited file is not a valid YAML mapping. Changes discarded.", err=True)
            return None
        return modified
    except Exception as e:
        click.echo(f"Error reading edited file: {e}. Changes discarded.", err=True)
        return None
    finally:
        temp_path.unlink(missing_ok=True)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("run-plan")
    def run_plan():
        """Manage run plans."""
        pass

    @run_plan.command("list")
    @click.argument(
        "directory",
        type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
        default=None,
        required=False,
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
        "--recursive",
        "-r",
        is_flag=True,
        default=True,
        help="Search recursively in subdirectories (default: true)",
    )
    @click.option(
        "--no-recursive",
        is_flag=True,
        default=False,
        help="Search only in the current directory",
    )
    @click.option(
        "--show-params",
        "-P",
        is_flag=True,
        default=False,
        help="Show placeholders and defaults for each plan",
    )
    def list_cmd(directory, fmt, recursive, no_recursive, show_params):
        """List all run.yaml plan files in the working directory."""
        if directory is not None:
            search_dir = directory
        else:
            common_config = load_common_config()
            workdir = common_config.get("workdir")
            if workdir:
                search_dir = Path(workdir)
            else:
                search_dir = Path.cwd()

        if not search_dir.exists():
            click.echo(f"Error: Directory {search_dir} does not exist", err=True)
            return

        if search_dir.is_file():
            if search_dir.name in ("run.yaml", "run.yml"):
                run_files = [search_dir]
            else:
                run_files = []
        else:
            is_recursive = recursive and not no_recursive
            run_files = find_run_yaml_files(search_dir, recursive=is_recursive)

        if fmt == "json":
            click.echo(
                json.dumps(
                    [
                        {
                            "path": str(f),
                            "relative_path": str(f.relative_to(Path.cwd())) if f.is_relative_to(Path.cwd()) else str(f),
                        }
                        for f in run_files
                    ],
                    indent=2,
                )
            )
            return

        if not run_files:
            click.echo(f"No run.yaml files found in {search_dir}")
            return

        click.echo(f"Found {len(run_files)} run plan(s) in {search_dir}:\n")
        for i, run_file in enumerate(run_files, 1):
            click.echo(f"  {i}. {run_file}")

            try:
                with open(run_file) as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "goal" in data:
                        goal = data["goal"]
                        if goal:
                            click.echo(f"     Goal: {goal}")

                    if isinstance(data, dict) and "plan" in data:
                        plan_steps = data["plan"]
                        if isinstance(plan_steps, list):
                            click.echo(f"     Steps: {len(plan_steps)}")

                    if show_params and isinstance(data, dict):
                        placeholders = _extract_placeholders(data)
                        if placeholders:
                            for name, info in sorted(placeholders.items()):
                                status = "required" if info["required"] else "optional"
                                default_str = f" (default: {info['default']})" if info["default"] else ""
                                click.echo(f"     Param: {name}  [{status}]{default_str}")
            except Exception:
                pass

            click.echo()

    @run_plan.command("params")
    @click.argument("plan", type=RunPlanFileType())
    def params_cmd(plan):
        """Show plan parameters (placeholders and defaults)."""
        plan_path = Path(plan)
        if not plan_path.exists():
            click.echo(f"Error: Plan file not found: {plan_path}", err=True)
            raise SystemExit(1)

        data = load_plan(plan_path)
        placeholders = _extract_placeholders(data)

        if not placeholders:
            click.echo(f"Plan: {plan_path}")
            click.echo("No parameters found — plan has no {{placeholders}}.")
            return

        click.echo(f"Plan: {plan_path}")
        if data.get("goal"):
            click.echo(f"Goal: {data['goal']}")
        click.echo(f"\nParameters:")
        for name, info in sorted(placeholders.items()):
            status = "required" if info["required"] else "optional"
            default_str = f" (default: {info['default']})" if info["default"] else ""
            click.echo(f"  {name}  [{status}]{default_str}")

    # -----------------------------------------------------------------------
    # EDIT subcommand — step wizard
    # -----------------------------------------------------------------------
    @run_plan.command("edit")
    @click.argument("plan", type=RunPlanFileType())
    def edit_cmd(plan):
        """Interactive wizard to edit a run plan's steps."""
        plan_path = Path(plan)
        if not plan_path.exists():
            click.echo(f"Error: Plan file not found: {plan_path}", err=True)
            raise SystemExit(1)

        data = load_plan(plan_path)
        goal = data.get("goal", "")
        steps = data.get("plan", [])

        click.echo(f"Editing plan: {plan_path}")
        if goal:
            click.echo(f"Goal: {goal}")
        click.echo(f"Steps: {len(steps)}\n")

        while True:
            # Display current steps
            if steps:
                click.echo("Current steps:")
                for i, step in enumerate(steps, 1):
                    click.echo(format_step(step, i))
                click.echo()
            else:
                click.echo("No steps yet.\n")

            # Choose action
            options = ["s", "e", "d", "m", "a", "c", "p", "l", "k", "q"]
            action = prompt_with_options(
                "Choose action — [S]how / [E]dit / [D]elete / [M]ove / [A]dd / [C]hange step (LLM) / [P]lan change (LLM) / [L]earn.md (auto-skill) / s[K]ill (auto-skill) / [Q]uit: ",
                options,
            )

            if action == "q":
                # Save and exit
                if steps:
                    save_plan(plan_path, data)
                    click.echo(f"\nPlan saved to {plan_path}")
                else:
                    click.echo("\nNo changes to save.")
                return

            elif action == "a":
                # Add new step
                step_type = prompt_with_options(
                    "Step type — [R]un skill / [T]ask / [A]sk user: ",
                    ["r", "t", "a"],
                    default="t",
                )

                new_step: dict = {"action": {"r": "run", "t": "task", "a": "ask"}[step_type]}

                if step_type == "r":
                    skill_name = prompt_free_text("Skill name: ")
                    if not skill_name:
                        click.echo("Aborted.")
                        continue
                    new_step["skill"] = skill_name

                    params_str = prompt_free_text("Parameters (KEY=VALUE,KEY2=VALUE2 or empty): ")
                    if params_str:
                        params = {}
                        for pair in params_str.split(","):
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                params[k.strip()] = v.strip()
                        if params:
                            new_step["params"] = params

                    inject = prompt_free_text("Inject instructions (optional, enter to skip): ")
                    if inject:
                        new_step["inject"] = inject

                elif step_type == "t":
                    desc = prompt_free_text("Task description: ")
                    if not desc:
                        click.echo("Aborted.")
                        continue
                    new_step["description"] = desc

                    instr = prompt_free_text("Additional instructions (optional): ")
                    if instr:
                        new_step["instructions"] = instr

                elif step_type == "a":
                    question = prompt_free_text("Question to ask user: ")
                    if not question:
                        click.echo("Aborted.")
                        continue
                    new_step["question"] = question

                # Where to insert
                if steps:
                    pos = prompt_free_text(f"Insert at position (1-{len(steps)+1}, default {len(steps)+1}): ")
                    try:
                        pos_idx = int(pos) - 1 if pos else len(steps)
                        pos_idx = max(0, min(pos_idx, len(steps)))
                    except ValueError:
                        pos_idx = len(steps)
                    steps.insert(pos_idx, new_step)
                else:
                    steps.append(new_step)

                # Re-number steps
                for i, s in enumerate(steps, 1):
                    s["step"] = i

                click.echo("Step added.\n")

            elif action == "p":
                # Plan-wide LLM change — doesn't need a step number
                _llm_change_plan(plan_path, data, steps)

            else:
                # Need a step number (for s, e, d, m, c)
                if not steps:
                    click.echo("No steps to modify. Add one first.\n")
                    continue

                step_num = prompt_free_text(f"Step number (1-{len(steps)}): ")
                try:
                    idx = int(step_num) - 1
                    if idx < 0 or idx >= len(steps):
                        click.echo(f"Invalid step number. Must be 1-{len(steps)}.\n")
                        continue
                except ValueError:
                    click.echo("Invalid number.\n")
                    continue

                if action == "s":
                    show_step_detail(steps[idx], idx + 1)

                elif action == "e":
                    original_step = steps[idx]
                    modified = edit_step_in_editor(original_step)
                    if modified is None:
                        click.echo("Edit cancelled.\n")
                    elif modified is original_step:
                        click.echo("No changes detected.\n")
                    elif "action" not in modified or modified["action"] not in ("run", "task", "ask"):
                        click.echo("Error: 'action' must be one of: run, task, ask. Changes discarded.", err=True)
                    else:
                        steps[idx] = modified
                        # Re-number
                        for i, s in enumerate(steps, 1):
                            s["step"] = i
                        # Save immediately
                        save_plan(plan_path, data)
                        click.echo(f"Step {idx + 1} updated and saved.\n")

                elif action == "d":
                    if prompt_confirm(f"Delete step {idx + 1}?"):
                        steps.pop(idx)
                        # Re-number
                        for i, s in enumerate(steps, 1):
                            s["step"] = i
                        click.echo("Step deleted.\n")

                elif action == "m":
                    target = prompt_free_text(f"Move to position (1-{len(steps)}): ")
                    try:
                        target_idx = int(target) - 1
                        if target_idx < 0 or target_idx >= len(steps):
                            click.echo(f"Invalid position. Must be 1-{len(steps)}.\n")
                            continue
                        step_to_move = steps.pop(idx)
                        steps.insert(target_idx, step_to_move)
                        # Re-number
                        for i, s in enumerate(steps, 1):
                            s["step"] = i
                        click.echo(f"Step moved to position {target_idx + 1}.\n")
                    except ValueError:
                        click.echo("Invalid number.\n")

                elif action == "c":
                    _llm_change_step(plan_path, data, steps, idx)

                elif action == "l":
                    _edit_auto_skill_learn(steps[idx])

                elif action == "k":
                    _edit_auto_skill_skill(steps[idx])

    # -----------------------------------------------------------------------
    # CONVERT-TASK-TO-SKILL subcommand — named tasks → auto-skills + new plan
    # -----------------------------------------------------------------------
    @run_plan.command("convert-task-to-skill")
    @click.argument("plan", type=RunPlanFileType())
    @click.option(
        "--reset",
        is_flag=True,
        default=False,
        help="Force recreation of auto-skills even if they already exist.",
    )
    def convert_task_to_skill_cmd(plan, reset):
        """Convert named tasks in a plan to auto-skills, output a new plan to stdout.

        For each task step with a 'name' field:
        1. Create an auto-{name} skill with parameters extracted from {{placeholders}}
        2. Generate a one-sentence description using LLM
        3. Save the original description as the skill body

        The new plan replaces named task steps with 'run' steps referencing the auto-skills,
        with parameters filled from the original task params or {{placeholder:default}} values.
        """
        plan_path = Path(plan)
        if not plan_path.exists():
            click.echo(f"Error: Plan file not found: {plan_path}", err=True)
            raise SystemExit(1)

        data = load_plan(plan_path)
        steps = data.get("plan", [])

        # Setup LLM
        from common.core.config import requires_common_config, load_tool_config
        from common.llm.registry import discover_providers, get_default_provider_name

        requires_common_config("skill", ["llm"])
        try:
            config = load_tool_config("skill")
            providers = discover_providers(config)
            provider_name = get_default_provider_name(config)
            llm = providers.get(provider_name)
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1)

        if not llm:
            click.echo(f"Error: provider '{provider_name}' not available.", err=True)
            raise SystemExit(1)

        new_steps = []
        skills_created = []

        for step in steps:
            action = step.get("action", "")
            task_name = step.get("name", "").strip() if action == "task" else ""

            if action == "task" and task_name:
                # This is a named task — convert to auto-skill
                description = step.get("description", "")
                params_from_step = {str(k): str(v) for k, v in (step.get("params") or {}).items()}

                # Create the auto-skill
                skill = _create_auto_skill(
                    task_name=task_name,
                    task_description=description,
                    reset=reset,
                    llm=llm,
                    model=None,
                )

                if skill is None:
                    click.echo(f"Error: Failed to create auto-skill for task '{task_name}'", err=True)
                    raise SystemExit(1)

                skills_created.append(skill.name)

                # Extract params from description to build step params
                desc_params = _extract_params_from_description(description)

                # Build params dict for the run step
                run_params = {}
                for p in desc_params:
                    pname = p["name"]
                    # Use value from step params if present, otherwise use {{key:default}}
                    if pname in params_from_step:
                        run_params[pname] = params_from_step[pname]
                    elif "default" in p:
                        run_params[pname] = f"{{{{{pname}:{p['default']}}}}}"
                    else:
                        run_params[pname] = f"{{{{{pname}}}}}"

                # Build new run step
                new_step = {
                    "step": 0,  # will be renumbered
                    "action": "run",
                    "skill": skill.name,
                }
                if run_params:
                    new_step["params"] = run_params
                if step.get("context_hint"):
                    new_step["context_hint"] = step["context_hint"]

                new_steps.append(new_step)
            else:
                # Keep non-named-task steps as-is
                new_steps.append(dict(step))

        # Renumber steps
        for i, s in enumerate(new_steps, 1):
            s["step"] = i

        # Build new plan
        new_plan_data = dict(data)
        new_plan_data["plan"] = new_steps

        # Print new plan to stdout (for redirection)
        output = yaml.dump(new_plan_data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        click.echo(output)

        # Print skill creation summary to stderr
        for name in skills_created:
            click.echo(f"Created skill: {name}", err=True)

    return CommandManifest(name="run-plan", click_command=run_plan)


# ---------------------------------------------------------------------------
# LLM-assisted single-step change (used from edit wizard)
# ---------------------------------------------------------------------------

def _llm_change_step(plan_path: Path, data: dict, steps: list, step_idx: int) -> None:
    """Interactive LLM chat to modify a single step."""
    from common.core.config import requires_common_config, load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name
    from core.skill import discover_skills
    from common.core.paths import get_skills_dir

    requires_common_config("skill", ["llm"])
    try:
        config = load_tool_config("skill")
        providers = discover_providers(config)
        provider_name = get_default_provider_name(config)
        llm = providers.get(provider_name)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        return

    if not llm:
        click.echo(f"Error: provider '{provider_name}' not available.", err=True)
        return

    skills = discover_skills(get_skills_dir())
    context = _build_llm_context(data, skills, step_idx)

    click.echo(f"\nLLM Chat — modifying step {step_idx + 1}: {steps[step_idx].get('action').upper()}")
    click.echo("Describe what you want to change.")
    click.echo("Type 'done' to finalize, 'abort' to cancel.\n")

    result = _run_llm_chat_loop(llm, None, context, data, plan_path, step_idx)
    if result:
        steps[step_idx] = result
        for i, s in enumerate(steps, 1):
            s["step"] = i
        save_plan(plan_path, data)
        click.echo(f"Plan saved to {plan_path}")


def _llm_change_plan(plan_path: Path, data: dict, steps: list) -> None:
    """Interactive LLM chat to modify the entire plan."""
    from common.core.config import requires_common_config, load_tool_config
    from common.llm.registry import discover_providers, get_default_provider_name
    from core.skill import discover_skills
    from common.core.paths import get_skills_dir

    requires_common_config("skill", ["llm"])
    try:
        config = load_tool_config("skill")
        providers = discover_providers(config)
        provider_name = get_default_provider_name(config)
        llm = providers.get(provider_name)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        return

    if not llm:
        click.echo(f"Error: provider '{provider_name}' not available.", err=True)
        return

    skills = discover_skills(get_skills_dir())
    # step_idx=None means whole plan
    context = _build_llm_context(data, skills, step_idx=None)

    click.echo(f"\nLLM Chat — modifying entire plan")
    click.echo("Describe what you want to change.")
    click.echo("Type 'done' to finalize, 'abort' to cancel.\n")

    result = _run_llm_chat_loop_for_plan(llm, None, context, data, plan_path)
    if result:
        # Replace the entire plan
        if isinstance(result, dict):
            if "plan" in result:
                # Full plan format: replace plan key
                data.update({k: v for k, v in result.items() if k != "plan"})
                steps.clear()
                steps.extend(result["plan"])
            else:
                # Just a dict of step-like keys: replace data entirely
                data.clear()
                data.update(result)
                # Re-fetch steps
                steps.clear()
                steps.extend(data.get("plan", []))
        # Re-number
        for i, s in enumerate(steps, 1):
            s["step"] = i
        save_plan(plan_path, data)
        click.echo(f"Plan saved to {plan_path}")


def _build_llm_context(plan_data: dict, skills: list, step_idx: int | None) -> str:
    """Build rich context for the LLM to understand the plan and available tools."""
    lines = []
    lines.append("# Run Plan Context")
    lines.append("")

    # Goal
    if plan_data.get("goal"):
        lines.append(f"## Goal")
        lines.append(plan_data["goal"])
        lines.append("")

    # Current plan
    lines.append("## Current Plan")
    lines.append("```yaml")
    lines.append(yaml.dump(plan_data, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip())
    lines.append("```")
    lines.append("")

    # Specific step being edited
    if step_idx is not None and step_idx < len(plan_data.get("plan", [])):
        step = plan_data["plan"][step_idx]
        lines.append(f"## Step {step_idx + 1} (being edited)")
        lines.append("```yaml")
        lines.append(yaml.dump(step, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip())
        lines.append("```")
        lines.append("")

    # Available skills
    if skills:
        lines.append("## Available Skills")
        lines.append("These skills can be used in 'run' steps. Each skill has parameters and instructions.")
        lines.append("")
        for skill in skills:
            lines.append(f"### {skill.name}")
            lines.append(f"Description: {skill.description or 'N/A'}")
            if skill.parameters:
                lines.append("Parameters:")
                for p in skill.parameters:
                    req = " (required)" if p.get("required") else ""
                    lines.append(f"  - {p['name']}{req}: {p.get('description', '')}")
            if skill.path and (skill.path / "scripts").exists():
                scripts = [f.name for f in (skill.path / "scripts").iterdir() if f.is_file()]
                lines.append(f"Scripts: {', '.join(scripts)}")
            lines.append("")

    # Instructions for the LLM
    lines.append("## Your Role")
    lines.append("You are an assistant helping the user modify their run plan.")
    lines.append("The user will describe what they want to change, and you will:")
    lines.append("1. Understand their intent")
    lines.append("2. Propose the modified YAML for the step (or new steps to add)")
    lines.append("3. Explain your changes")
    lines.append("4. Wait for their feedback or approval")
    lines.append("")

    # YAML syntax reference (always included so LLM produces valid output)
    lines.append("## Run Plan YAML Syntax Reference")
    lines.append("")
    lines.append("Top-level keys: `goal`, `success_criteria` (optional), `preparation_plan` (optional), `plan` (list of steps).")
    lines.append("")
    lines.append("Each step is a YAML mapping with:")
    lines.append("- `step`: integer (1-based, must be sequential)")
    lines.append("- `action`: one of `run`, `task`, `ask`")
    lines.append("")
    lines.append("### For `action: run`")
    lines.append("- `skill`: (string) exact skill name from the Available Skills list above")
    lines.append("- `params`: (dict) key-value pairs matching the skill's parameters")
    lines.append("- `inject`: (optional string) additional instructions appended to the skill's body")
    lines.append("- `context_hint`: (optional string) hint for auto-chaining and context extraction")
    lines.append("")
    lines.append("### For `action: task`")
    lines.append("- `description`: (string) free-form task description")
    lines.append("- `instructions`: (optional string) additional execution instructions")
    lines.append("- `name`: (optional string) task name — used by run-plan convert-task-to-skill to create `auto-{name}` skill")
    lines.append("- `context_hint`: (optional string) hint for context extraction")
    lines.append("")
    lines.append("### For `action: ask`")
    lines.append("- `question`: (string) question presented to the user")
    lines.append("")
    lines.append("### Placeholders")
    lines.append("- `{{key}}` — mandatory parameter, substituted at import time")
    lines.append("- `{{key:default}}` — optional parameter with default value")
    lines.append("")
    lines.append("### YAML Formatting Rules")
    lines.append("- Each step in the `plan` list starts with `- step: N` (dash + space)")
    lines.append("- Multi-line values or values with colons (:), commas, apostrophes MUST be double-quoted")
    lines.append("- Nested dicts like `params:` must have each key on its own indented line")
    lines.append("- Do NOT use inline flow style `{key: value}` for params")
    lines.append("")
    lines.append("Example:")
    lines.append("```yaml")
    lines.append("goal: \"Analyze {{video_url}}\"")
    lines.append("plan:")
    lines.append("  - step: 1")
    lines.append("    action: run")
    lines.append("    skill: my-analyse")
    lines.append("    params:")
    lines.append("      url: \"{{video_url}}\"")
    lines.append("    context_hint: \"Result will be used by next step\"")
    lines.append("  - step: 2")
    lines.append("    action: task")
    lines.append("    name: find-videos")
    lines.append("    description: \"Search for videos about the analyzed topic\"")
    lines.append("  - step: 3")
    lines.append("    action: ask")
    lines.append("    question: \"Which videos should we use?\"")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _clean_llm_yaml(raw: str) -> str | None:
    """Robustly clean LLM output to produce parseable YAML.
    
    Handles: markdown code fences, stray text outside YAML, unquoted values
    with colons, and other common LLM formatting issues.
    """
    import re

    text = raw.strip()
    if not text:
        return None

    # 1. Strip markdown code fences (at start or embedded)
    if "```" in text:
        # Try to extract content between ```yaml and ```
        fence_pattern = re.compile(r"```(?:yaml)?\s*\n(.*?)\n\s*```", re.DOTALL)
        match = fence_pattern.search(text)
        if match:
            text = match.group(1).strip()
        else:
            # Fallback: strip all ``` lines
            lines = [l for l in text.splitlines() if l.strip() not in ("```", "```yaml")]
            text = "\n".join(lines)

    # 2. Try to parse directly first (fast path)
    import yaml
    try:
        result = yaml.safe_load(text)
        if isinstance(result, dict):
            return text
    except Exception:
        pass

    # 3. Extract YAML-like content: find first and last YAML-looking lines
    known_keys = ["action:", "step:", "skill:", "description:", "question:",
                  "context_hint:", "params:", "inject:", "instructions:"]
    
    lines = text.splitlines()
    first_yaml = -1
    last_yaml = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(stripped.startswith(k) for k in known_keys):
            if first_yaml == -1:
                first_yaml = i
            last_yaml = i
        elif re.match(r"^[a-z_][a-z_0-9]*:", stripped):
            if first_yaml == -1:
                first_yaml = i
            last_yaml = i

    if first_yaml == -1:
        return None

    yaml_text = "\n".join(lines[first_yaml:last_yaml + 1])

    # 4. Fix unquoted values containing colons
    fixed_lines = []
    for line in yaml_text.splitlines():
        m = re.match(r"^(\s*)([a-z_][a-z_0-9]*:\s*)(.*)", line)
        if m:
            indent, key_part, value = m.groups()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                fixed_lines.append(line)
                continue
            if ":" in value:
                value = value.replace('"', '\\"')
                value = f'"{value}"'
            fixed_lines.append(f"{indent}{key_part}{value}")
        else:
            fixed_lines.append(line)

    yaml_text = "\n".join(fixed_lines)

    # 5. Final validation
    try:
        result = yaml.safe_load(yaml_text)
        if isinstance(result, dict):
            return yaml_text
    except Exception:
        pass

    return None


def _run_llm_chat_loop(
    llm,
    model: str | None,
    context: str,
    plan_data: dict,
    plan_path: Path,
    step_idx: int | None,
) -> dict | None:
    """Run an interactive chat loop with the LLM for plan editing.
    Returns the modified step dict if accepted, or None if cancelled.
    """
    from common.llm.base import LLMRequest
    from prompt_toolkit import prompt
    from core.repl import REPL_STYLE

    messages = []
    system_prompt = (
        "You are helping a user edit a single step in a run plan (YAML file) for the fast-market skill runner. "
        "The user will describe the changes they want. "
        "Propose YAML modifications and explain your reasoning.\n\n"
        "CRITICAL: When the user says 'done', output ONLY the final modified step as a YAML mapping. "
        "A step is a single YAML mapping with keys like: step, action, skill/params/description/etc.\n\n"
        "YAML RULES:\n"
        "- NEVER use markdown code fences. Output raw YAML only.\n"
        "- If a value contains colons (:), commas, apostrophes, or parentheses, you MUST wrap it in double quotes.\n"
        "- `params` must be a proper YAML dict with each key on its own indented line.\n"
        "- Do NOT use inline flow style `{key: value}`.\n\n"
        "Step format examples:\n"
        "action: run\n"
        "skill: my-skill\n"
        "params:\n"
        '  url: "https://example.com"\n\n'
        "action: task\n"
        "name: find-videos\n"
        'description: "Search for related videos"\n\n'
        "action: ask\n"
        'question: "What should we do next?"'
    )

    while True:
        try:
            user_input = prompt("You> ", style=REPL_STYLE).strip()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nAborted — no changes saved.")
            return None

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q", "abort"):
            click.echo("Aborted — no changes saved.")
            return None

        if user_input.lower() == "done":
            messages.append({"role": "user", "content": "done — output ONLY the final modified YAML. Nothing else."})
            req = LLMRequest(
                system=system_prompt,
                messages=[{"role": "system", "content": context}] + messages,
                model=model,
                temperature=0.3,
            )
            resp = llm.complete(req)
            final_yaml = resp.content.strip()

            click.echo("\n" + "=" * 60)
            click.echo("Final proposed YAML:")
            click.echo("=" * 60)
            click.echo(final_yaml)
            click.echo("=" * 60)

            try:
                import yaml as yaml_lib
                import re as _re

                cleaned = _clean_llm_yaml(final_yaml)
                if not cleaned:
                    click.echo("Error: no YAML content found.", err=True)
                    messages.pop()
                    continue

                parsed = yaml_lib.safe_load(cleaned)
                if not isinstance(parsed, dict):
                    click.echo("Error: LLM did not output a valid YAML mapping.", err=True)
                    messages.pop()
                    continue

                if prompt_confirm("Accept and save these changes?"):
                    return parsed
                else:
                    click.echo("Changes not saved. Continue chatting, type 'abort' to cancel.\n")
                    messages.pop()
                    continue

            except Exception as e:
                click.echo(f"Error parsing YAML: {e}", err=True)
                click.echo("Continue chatting, or type 'abort' to cancel.\n")
                messages.pop()
                continue

        messages.append({"role": "user", "content": user_input})
        req = LLMRequest(
            system=system_prompt,
            messages=[{"role": "system", "content": context}] + messages,
            model=model,
            temperature=0.7,
        )

        click.echo("Thinking...", err=True)
        try:
            resp = llm.complete(req)
            click.echo(f"\nAssistant: {resp.content}\n")
            messages.append({"role": "assistant", "content": resp.content})
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            messages.pop()

    return None
# Appended to run-plan/register.py

def _run_llm_chat_loop_for_plan(
    llm,
    model: str | None,
    context: str,
    plan_data: dict,
    plan_path: Path,
) -> dict | None:
    """Run an interactive chat loop with the LLM for editing the entire plan.
    Returns the modified plan dict if accepted, or None if cancelled.
    """
    from common.llm.base import LLMRequest
    from prompt_toolkit import prompt
    from core.repl import REPL_STYLE

    messages = []
    system_prompt = (
        "You are helping a user edit a run plan (YAML file) for the fast-market skill runner. "
        "The user will describe the changes they want. "
        "Propose YAML modifications and explain your reasoning.\n\n"
        "CRITICAL: When the user says 'done', output ONLY the full modified plan YAML. "
        "The plan must have these top-level keys: 'goal' and 'plan' (list of steps). "
        "Each step must have 'step' (number), 'action' (run/task/ask). "
        "For 'run' steps: 'skill' and optionally 'params', 'inject', 'context_hint'. "
        "For 'task' steps: 'description' and optionally 'instructions', 'context_hint', 'name'. "
        "For 'ask' steps: 'question'.\n\n"
        "CRITICAL YAML RULES:\n"
        "- NEVER use markdown code fences (```yaml ... ```). Output raw YAML only.\n"
        "- If a value contains colons (:), commas, apostrophes, or parentheses, you MUST wrap it in double quotes.\n"
        "- Use proper YAML list syntax: each step starts with '- step: N' (dash + space).\n"
        "- Nested dicts like 'params:' must be indented under their key, each key on its own line.\n"
        "- 'name' field on a task step is used by convert-task-to-skill (creates auto-{name} skill).\n"
        "- {{placeholders}} like {{video_url}} or {{count:5}} can appear in any string value.\n\n"
        "VALID PLAN YAML EXAMPLE:\n"
        "goal: \"Analyze and promote a video\"\n"
        "success_criteria: \"At least 5 replies generated\"\n"
        "plan:\n"
        "  - step: 1\n"
        "    action: run\n"
        "    skill: my-analyse\n"
        "    params:\n"
        "      url: \"{{video_url}}\"\n"
        "    context_hint: \"Analysis result for {{video_url}}\"\n"
        "  - step: 2\n"
        "    action: task\n"
        "    name: find-videos\n"
        "    description: \"Search YouTube for videos about the same topic as the analyzed video\"\n"
        "    instructions: \"Find at least 5 related videos using keywords from step 1\"\n"
        "    context_hint: \"List of related video URLs\"\n"
        "  - step: 3\n"
        "    action: ask\n"
        "    question: \"Which videos should we prioritize?\"\n\n"
        "INVALID (will cause errors):\n"
        "- Missing dash before 'step:' in the plan list\n"
        "- 'description' value with unquoted colon\n"
        "- 'params' as inline {key: value} instead of proper YAML dict\n\n"
        "When the user says 'done', output ONLY the full modified plan YAML. Nothing else."
    )

    while True:
        try:
            user_input = prompt("You> ", style=REPL_STYLE).strip()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nAborted — no changes saved.")
            return None

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q", "abort"):
            click.echo("Aborted — no changes saved.")
            return None

        if user_input.lower() == "done":
            messages.append({"role": "user", "content": "done — output ONLY the full modified plan YAML. Nothing else."})
            req = LLMRequest(
                system=system_prompt,
                messages=[{"role": "system", "content": context}] + messages,
                model=model,
                temperature=0.3,
            )
            resp = llm.complete(req)
            final_yaml = resp.content.strip()

            click.echo("\n" + "=" * 60)
            click.echo("Final proposed YAML:")
            click.echo("=" * 60)
            click.echo(final_yaml)
            click.echo("=" * 60)

            try:
                import yaml as yaml_lib

                cleaned = _clean_llm_yaml(final_yaml)
                if not cleaned:
                    click.echo("Error: no YAML content found.", err=True)
                    messages.pop()
                    continue

                parsed = yaml_lib.safe_load(cleaned)
                if not isinstance(parsed, dict):
                    click.echo("Error: LLM did not output a valid YAML mapping.", err=True)
                    messages.pop()
                    continue

                if not parsed.get("plan"):
                    click.echo("Error: plan must have a 'plan' key with a list of steps.", err=True)
                    messages.pop()
                    continue

                if prompt_confirm("Accept and save these changes?"):
                    return parsed
                else:
                    click.echo("Changes not saved. Continue chatting, type 'abort' to cancel.\n")
                    messages.pop()
                    continue

            except Exception as e:
                click.echo(f"Error parsing YAML: {e}", err=True)
                click.echo("Continue chatting, or type 'abort' to cancel.\n")
                messages.pop()
                continue

        messages.append({"role": "user", "content": user_input})
        req = LLMRequest(
            system=system_prompt,
            messages=[{"role": "system", "content": context}] + messages,
            model=model,
            temperature=0.7,
        )

        click.echo("Thinking...", err=True)
        try:
            resp = llm.complete(req)
            click.echo(f"\nAssistant: {resp.content}\n")
            messages.append({"role": "assistant", "content": resp.content})
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            messages.pop()

    return None


# ---------------------------------------------------------------------------
# Auto-skill editing helpers
# ---------------------------------------------------------------------------

def _get_auto_skill_path(step: dict) -> Path | None:
    """Get the path to the auto-skill for a task step, if it exists."""
    from common.core.paths import get_skills_dir

    task_name = step.get("name", "").strip()
    if not task_name:
        return None

    skill_name = f"auto-{task_name}"
    skill_path = get_skills_dir() / skill_name

    if skill_path.exists() and (skill_path / "SKILL.md").exists():
        return skill_path
    return None


def _edit_auto_skill_learn(step: dict) -> None:
    """Edit the LEARN.md file of the auto-skill for a task step."""
    from common.cli.helpers import open_editor

    task_name = step.get("name", "").strip()
    if not task_name or step.get("action") != "task":
        click.echo("This step is not a named task (no auto-skill).\n")
        return

    skill_path = _get_auto_skill_path(step)
    if not skill_path:
        click.echo(f"Auto-skill 'auto-{task_name}' does not exist yet.\n")
        return

    learn_path = skill_path / "LEARN.md"
    
    # Create LEARN.md if it doesn't exist
    if not learn_path.exists():
        learn_path.write_text("# Lessons Learned\n\n", encoding="utf-8")

    click.echo(f"Opening LEARN.md for auto-{task_name}...")
    try:
        open_editor(learn_path)
        click.echo("LEARN.md saved.\n")
    except Exception as e:
        click.echo(f"Error editing LEARN.md: {e}\n", err=True)


def _edit_auto_skill_skill(step: dict) -> None:
    """Edit the SKILL.md file of the auto-skill for a task step."""
    from common.cli.helpers import open_editor

    task_name = step.get("name", "").strip()
    if not task_name or step.get("action") != "task":
        click.echo("This step is not a named task (no auto-skill).\n")
        return

    skill_path = _get_auto_skill_path(step)
    if not skill_path:
        click.echo(f"Auto-skill 'auto-{task_name}' does not exist yet.\n")
        return

    skill_md_path = skill_path / "SKILL.md"

    click.echo(f"Opening SKILL.md for auto-{task_name}...")
    try:
        open_editor(skill_md_path)
        click.echo("SKILL.md saved.\n")
    except Exception as e:
        click.echo(f"Error editing SKILL.md: {e}\n", err=True)


# ---------------------------------------------------------------------------
# convert-task-to-skill helpers
# ---------------------------------------------------------------------------

def _extract_params_from_description(text: str) -> list[dict]:
    """Extract {{key}} and {{key:default}} placeholders from text.

    Returns a list of parameter dicts with name, description, required, and default fields.
    """
    import re
    params = []
    seen = set()

    for m in re.finditer(r"\{\{([^}]+)\}\}", text):
        inner = m.group(1).strip()
        if ":" in inner:
            key, default = inner.split(":", 1)
            key = key.strip()
            default = default.strip()
        else:
            key = inner
            default = None

        if key not in seen:
            seen.add(key)
            param = {
                "name": key,
                "description": f"Parameter {key}",
                "required": default is None,
            }
            if default is not None:
                param["default"] = default
            params.append(param)

    return params


def _convert_placeholders_to_skill_format(text: str) -> str:
    """Convert {{key}} and {{key:default}} to {key} for skill runtime substitution."""
    import re
    return re.sub(r"\{\{([^}]+)\}\}", lambda m: "{" + m.group(1).split(":")[0].strip() + "}", text)


def _generate_parameters_yaml(params: list[dict]) -> str:
    """Generate YAML parameters section for SKILL.md frontmatter."""
    if not params:
        return ""

    lines = ["parameters:"]
    for p in params:
        pname = p['name']
        desc = p.get('description', f'Parameter {pname}')
        lines.append(f"  - name: {pname}")
        lines.append(f"    description: {desc}")
        if "default" in p:
            lines.append(f"    default: {p['default']}")
        elif p.get("required", True):
            lines.append(f"    required: true")
    return "\n".join(lines)


def _llm_skill_summary(description: str, llm, model: str | None) -> str:
    """Use LLM to generate a one-sentence summary of a skill from its description."""
    from common.llm.base import LLMRequest

    prompt = (
        "You are given a skill description. Produce a single, concise sentence "
        "(max 25 words) summarizing what the skill does. Output ONLY the sentence, "
        "no extra text, no quotes, no explanation.\n\n"
        f"Skill description:\n{description}"
    )

    req = LLMRequest(
        system="You summarize skill descriptions in one sentence.",
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.3,
    )
    resp = llm.complete(req)
    return resp.content.strip().strip('"').strip("'").strip()


def _create_auto_skill(
    task_name: str,
    task_description: str,
    reset: bool,
    llm,
    model: str | None,
):
    """Create an auto-skill from a named task description.

    1. Extract {{...}} params from description
    2. Generate one-sentence summary via LLM
    3. Write SKILL.md with params, summary as description, original description as body

    Returns the Skill object, or None if creation failed.
    """
    from common.core.paths import get_skills_dir
    from core.skill import Skill

    skill_name = f"auto-{task_name}"
    skill_path = get_skills_dir() / skill_name

    # Check if skill already exists on disk (unless reset mode)
    if not reset and skill_path.exists():
        existing = Skill.from_path(skill_path)
        if existing:
            click.echo(f"[convert] Skill already exists: {skill_name}", err=True)
            return existing

    # Remove existing skill if reset mode
    if reset and skill_path.exists():
        import shutil
        try:
            shutil.rmtree(skill_path)
        except Exception as exc:
            click.echo(f"[convert] Warning: Failed to remove skill {skill_name}: {exc}", err=True)

    # Extract parameters from task description
    params_list = _extract_params_from_description(task_description)
    params_yaml = _generate_parameters_yaml(params_list)

    # Generate one-sentence summary via LLM
    click.echo(f"[convert] Generating summary for: {skill_name}", err=True)
    try:
        summary = _llm_skill_summary(task_description, llm, model)
    except Exception as exc:
        click.echo(f"[convert] LLM summary failed for {skill_name}, using fallback: {exc}", err=True)
        summary = task_description.split("\n")[0][:120]

    # Convert placeholders from {{key:default}} to {key} for skill runtime
    body = _convert_placeholders_to_skill_format(task_description)

    # Build skill content
    try:
        skill_path.mkdir(parents=True, exist_ok=True)

        # Build frontmatter
        frontmatter = f"""---
name: {skill_name}
description: {summary}
"""
        if params_yaml:
            frontmatter += params_yaml + "\n"
        frontmatter += "---"

        skill_content = f"""{frontmatter}

# {skill_name}

## Instructions

{body}
"""
        (skill_path / "SKILL.md").write_text(skill_content, encoding="utf-8")
        click.echo(f"[convert] Created skill: {skill_name}", err=True)
        return Skill.from_path(skill_path)
    except Exception as exc:
        click.echo(f"[convert] Failed to create skill {skill_name}: {exc}", err=True)
        return None
