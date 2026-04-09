"""
Shared utilities for plan import/export and placeholder substitution.

These utilities are used by both `skill run` and `skill exec` commands.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click
import yaml

from core.router import SkillPlan, SkillPlanStep


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------


def substitute_placeholders(obj: Any, params: dict[str, str]) -> Any:
    """Recursively replace {{key}} and {{key:default}} placeholders in string values.

    Supports two forms:
    - {{key}} — mandatory, errors if not in params
    - {{key:default}} — optional, uses 'default' if key not in params
    """
    if isinstance(obj, str):
        def _replace(m):
            inner = m.group(1)  # e.g. "key" or "key:default"
            if ":" in inner:
                key, default = inner.split(":", 1)
                return params.get(key.strip(), default) if params else default
            else:
                return params.get(inner, m.group(0)) if params else m.group(0)
        return re.sub(r"\{\{([^}]+)\}\}", _replace, obj)
    if isinstance(obj, dict):
        return {k: substitute_placeholders(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_placeholders(item, params) for item in obj]
    return obj


def find_missing_placeholders(obj: Any, path: str = "") -> list[str]:
    """Find remaining unsubstituted mandatory {{key}} placeholders.

    Only reports {{key}} without defaults as missing.
    {{key:default}} that resolved to the default are NOT missing.
    """
    missing = []
    if isinstance(obj, str):
        # Find all remaining {{...}} patterns
        for m in re.finditer(r"\{\{([^}]+)\}\}", obj):
            inner = m.group(1)
            if ":" not in inner:
                missing.append(inner.strip())
    elif isinstance(obj, dict):
        for k, v in obj.items():
            missing.extend(find_missing_placeholders(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            missing.extend(find_missing_placeholders(item, f"{path}[{i}]"))
    return missing


# ---------------------------------------------------------------------------
# Plan import
# ---------------------------------------------------------------------------


def import_plan_from_yaml(
    filepath: str, workdir: str = ".", params: dict[str, str] | None = None
) -> SkillPlan:
    """Import a skill plan from YAML file, substituting {{key}} placeholders with params."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {filepath}")

    # Read raw data BEFORE substitution
    raw_data = yaml.safe_load(path.read_text())
    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid plan YAML format in {filepath}")

    # Apply placeholder substitution (including defaults for {{key:default}} patterns)
    data = substitute_placeholders(dict(raw_data), params)

    # Check for remaining unsubstituted mandatory placeholders
    missing = find_missing_placeholders(data)
    if missing:
        raise ValueError(
            f"Unresolved mandatory placeholders in plan: {', '.join(set(missing))}. "
            f"Provide values with -p/--param options."
        )

    goal = data.get("goal", "")
    if not goal:
        raise ValueError(f"Plan missing 'goal' field in {filepath}")

    plan_steps = []
    plan_data = data.get("plan", [])
    raw_plan_data = raw_data.get("plan", [])

    for i, step_dict in enumerate(plan_data, 1):
        action = step_dict.get("action", "")
        if action not in ("run", "task", "ask"):
            raise ValueError(f"Step {i} has invalid action: {action}")

        # Get original (pre-substitution) values
        raw_step = raw_plan_data[i - 1] if i - 1 < len(raw_plan_data) else {}
        original_desc = raw_step.get("description", "")
        original_params = raw_step.get("params", {}) or {}

        step = SkillPlanStep(
            step=i,
            action=action,
            skill_name=step_dict.get("skill", ""),
            params=step_dict.get("params", {}),
            original_params=original_params,
            inject=step_dict.get("inject", ""),
            description=step_dict.get("description", ""),
            original_description=original_desc,
            instructions=step_dict.get("instructions", ""),
            question=step_dict.get("question", ""),
            context_hint=step_dict.get("context_hint", ""),
            name=step_dict.get("name", ""),
        )
        plan_steps.append(step)

    return SkillPlan(
        goal=goal,
        steps=plan_steps,
        success_criteria=data.get("success_criteria", ""),
        preparation_plan=data.get("preparation_plan", ""),
    )


# ---------------------------------------------------------------------------
# Plan file type for Click (used by skill exec)
# ---------------------------------------------------------------------------


class RunPlanFileType(click.ParamType):
    """Click parameter type for run plan YAML files."""
    name = "RUN_PLAN"

    def __init__(self, workdir: str | None = None):
        self.workdir = workdir

    def _get_workdir(self) -> Path:
        """Get the workdir from common config or fallback to cwd."""
        if self.workdir:
            return Path(self.workdir).expanduser().resolve()
        try:
            from common.core.config import load_common_config
            common_config = load_common_config()
            workdir_path = common_config.get("workdir")
            return (
                Path(workdir_path).expanduser().resolve()
                if workdir_path
                else Path.cwd()
            )
        except Exception:
            return Path.cwd()

    def _find_run_plans(self, workdir: Path):
        """Find all run.yaml/run.yml files recursively."""
        plans = []
        for pattern in ["run.yaml", "run.yml"]:
            plans.extend(workdir.rglob(pattern))
        return sorted(set(plans))

    def shell_complete(self, ctx, param, incomplete):
        from click.shell_completion import CompletionItem

        cwd = self._get_workdir()
        if not cwd.exists() or not cwd.is_dir():
            return []

        plans = self._find_run_plans(cwd)
        items = []

        for plan_path in plans:
            try:
                rel = plan_path.relative_to(cwd).as_posix()
            except ValueError:
                rel = str(plan_path)

            if not rel.startswith(incomplete):
                continue

            # Try to read goal for help text
            help_text = ""
            try:
                data = yaml.safe_load(plan_path.read_text())
                if isinstance(data, dict) and data.get("goal"):
                    help_text = data["goal"]
            except Exception:
                pass

            items.append(CompletionItem(rel, help=help_text))

        return items

    def convert(self, value, param, ctx):
        # If it's a relative path, resolve against workdir
        path = Path(value)
        if not path.is_absolute():
            workdir = self._get_workdir()
            path = workdir / path
        return path.resolve()


# Keep backwards compatibility alias
_substitute_placeholders = substitute_placeholders
_find_missing_placeholders = find_missing_placeholders
_import_plan_from_yaml = import_plan_from_yaml
