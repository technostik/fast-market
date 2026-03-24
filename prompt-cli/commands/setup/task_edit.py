from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from common.core.config import _resolve_config_path, load_tool_config
from commands.setup import load_config, save_config, init_task_config


def _get_editor() -> str:
    editor = (
        subprocess.run(
            ["git", "var", "GIT_EDITOR"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or subprocess.run(
            ["sed", "-n", "s/^.*EDITOR.//p", "/etc/environment"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "nano"
    )
    return editor


def edit_task_config() -> bool:
    """Edit the full prompt.yaml config file."""
    config_path = _resolve_config_path("prompt")
    config = load_config(config_path)
    init_task_config(config)

    yaml_content = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="fastmarket-", delete=False
    ) as f:
        f.write(yaml_content)
        temp_path = Path(f.name)

    try:
        editor = _get_editor()
        subprocess.run([editor, str(temp_path)], check=True)

        new_content = temp_path.read_text()
        new_config = yaml.safe_load(new_content)

        if new_config is None or not isinstance(new_config, dict):
            print("Error: Invalid YAML format", file=sys.stderr)
            return False

        errors = _validate_full_config(new_config)
        if errors:
            print("Validation errors:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return False

        save_config(config_path, new_config)
        print(f"Configuration saved to: {config_path}")
        return True

    finally:
        temp_path.unlink(missing_ok=True)


def _validate_task_config(task: dict) -> list[str]:
    errors = []

    if "max_iterations" in task:
        if not isinstance(task["max_iterations"], int) or task["max_iterations"] < 1:
            errors.append("max_iterations must be a positive integer")

    if "default_timeout" in task:
        if not isinstance(task["default_timeout"], int) or task["default_timeout"] < 1:
            errors.append("default_timeout must be a positive integer")

    if "fastmarket_tools" in task:
        ft = task["fastmarket_tools"]
        if not isinstance(ft, dict):
            errors.append("fastmarket_tools must be a mapping")
        else:
            for name, config in ft.items():
                if isinstance(config, dict):
                    if "description" not in config and "commands" not in config:
                        errors.append(
                            f"fastmarket_tools.{name} should have 'description' and/or 'commands'"
                        )
                elif not isinstance(config, str):
                    errors.append(
                        f"fastmarket_tools.{name} must be a mapping or string"
                    )

    if "system_commands" in task:
        if not isinstance(task["system_commands"], list):
            errors.append("system_commands must be a list")
        elif not all(isinstance(c, str) for c in task["system_commands"]):
            errors.append("system_commands must contain only strings")

    if "agent_prompt" in task:
        ap = task["agent_prompt"]
        if not isinstance(ap, dict):
            errors.append("agent_prompt must be a mapping")
        else:
            templates = ap.get("templates", {})
            if not isinstance(templates, dict):
                errors.append("agent_prompt.templates must be a mapping")
            else:
                for name, tpl in templates.items():
                    if not isinstance(tpl, dict):
                        errors.append(
                            f"agent_prompt.templates.{name} must be a mapping"
                        )
                    elif "template" not in tpl:
                        errors.append(
                            f"agent_prompt.templates.{name} must have 'template' field"
                        )

    if "tools_doc" in task:
        td = task["tools_doc"]
        if not isinstance(td, dict):
            errors.append("tools_doc must be a mapping")
        else:
            templates = td.get("templates", {})
            if not isinstance(templates, dict):
                errors.append("tools_doc.templates must be a mapping")
            else:
                for name, tpl in templates.items():
                    if not isinstance(tpl, dict):
                        errors.append(f"tools_doc.templates.{name} must be a mapping")
                    elif "template" not in tpl:
                        errors.append(
                            f"tools_doc.templates.{name} must have 'template' field"
                        )

    return errors


def _validate_full_config(config: dict) -> list[str]:
    errors = []

    if "task" in config:
        task_errors = _validate_task_config(config["task"])
        for err in task_errors:
            errors.append(f"task.{err}")

    if "providers" in config:
        if not isinstance(config["providers"], dict):
            errors.append("providers must be a mapping")

    return errors


def show_task_config() -> None:
    """Show the full system prompt that the LLM will receive."""
    from common.core.config import _resolve_config_path

    config_path = _resolve_config_path("prompt")
    config = load_config(config_path)
    task = init_task_config(config)
    save_config(config_path, config)

    from commands.task.prompts import build_system_prompt

    fastmarket_tools = task.get("fastmarket_tools", {})
    system_commands = task.get("system_commands", [])
    system_prompt = build_system_prompt(
        task_description="[TASK_PLACEHOLDER]",
        fastmarket_tools_config=fastmarket_tools,
        system_commands=system_commands,
        workdir=Path.cwd(),
        task_params=None,
    )
    print(system_prompt)
