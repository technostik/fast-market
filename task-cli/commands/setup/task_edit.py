from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml
from commands.setup import load_task_config, save_task_config, init_task_config

from common.cli.helpers import get_editor


def edit_task_config() -> bool:
    """Edit the full task config file."""
    config_path = _resolve_config_path("task")
    config = load_task_config()
    task = init_task_config(config)

    yaml_content = dump_yaml({"task": task}, sort_keys=False)

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="fastmarket-", delete=False
    ) as f:
        f.write(yaml_content)
        temp_path = Path(f.name)

    try:
        editor = get_editor()
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

        save_task_config(new_config)
        print(f"Configuration saved to: {config_path}")
        return True

    finally:
        temp_path.unlink(missing_ok=True)


def _validate_full_config(config: dict) -> list[str]:
    errors = []

    if "task" in config:
        task = config["task"]
        if not isinstance(task, dict):
            errors.append("task must be a mapping")
        else:
            task_errors = _validate_task_config(task)
            for err in task_errors:
                errors.append(f"task.{err}")

    return errors


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
            for name, conf in ft.items():
                if isinstance(conf, dict):
                    if "description" not in conf and "commands" not in conf:
                        errors.append(
                            f"fastmarket_tools.{name} should have 'description' and/or 'commands'"
                        )
                elif not isinstance(conf, str):
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
