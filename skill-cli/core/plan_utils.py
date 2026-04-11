"""
Shared utilities for plan import/export and placeholder substitution.

These utilities are used by both `skill run` and `skill exec` commands.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml


# ---------------------------------------------------------------------------
# Plan data models
# ---------------------------------------------------------------------------


@dataclass
class SkillPlanStep:
    """A single step in a skill execution plan.

    Note: In the new format, steps do NOT declare their own params.
    Global params from the plan's 'params:' section are automatically
    injected into skills at runtime based on the skill's parameter declarations.
    """
    step: int
    action: str  # "run", "task", "ask"
    skill_name: str = ""  # for action="run"
    params: dict[str, str] = field(default_factory=dict)  # Deprecated: use global params instead
    inject: str = ""  # injected instructions for action="run"
    description: str = ""  # for action="task"
    instructions: str = ""  # additional instructions for action="task"
    question: str = ""  # for action="ask"
    context_hint: str = ""  # hint about context needed
    name: str = ""  # task name, used by plan convert-task-to-skill
    original_description: str = ""  # original description before placeholder substitution
    original_params: dict[str, str] = field(default_factory=dict)  # Deprecated: use global params instead


@dataclass
class SkillPlan:
    """A complete execution plan exported from the router."""
    goal: str
    steps: list[SkillPlanStep] = None
    success_criteria: str = ""
    preparation_plan: str = ""


# ---------------------------------------------------------------------------
# Global plan params
# ---------------------------------------------------------------------------


@dataclass
class PlanParamDef:
    """A single parameter definition from the global params section."""
    name: str
    default: str | None = None  # None means mandatory (must be provided via CLI)

    @property
    def is_mandatory(self) -> bool:
        return self.default is None


def parse_global_params(params_list: list) -> list[PlanParamDef]:
    """Parse the global params list from YAML.

    Supports two formats:
    - "PARAM_NAME" (mandatory, must be provided via CLI)
    - "PARAM_NAME:default_value" (optional, uses default if not provided via CLI)
    """
    if not params_list:
        return []

    result = []
    for item in params_list:
        if isinstance(item, str):
            if ":" in item:
                name, default = item.split(":", 1)
                result.append(PlanParamDef(name=name.strip(), default=default.strip()))
            else:
                result.append(PlanParamDef(name=item.strip(), default=None))
        else:
            raise ValueError(f"Invalid param definition: {item!r}. Expected 'NAME' or 'NAME:default'")

    return result


def build_params_dict(
    param_defs: list[PlanParamDef],
    cli_params: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the final params dict from global param definitions and CLI overrides.

    - CLI params override global defaults
    - If CLI doesn't provide a value and global has a default, use the default
    - If CLI doesn't provide a value and no default exists, the param is missing (will be validated later)
    """
    cli_params = cli_params or {}
    result = {}

    for param_def in param_defs:
        if param_def.name in cli_params:
            # CLI overrides global default
            result[param_def.name] = cli_params[param_def.name]
        elif param_def.default is not None:
            # Use global default
            result[param_def.name] = param_def.default
        # else: mandatory param not provided by CLI, will be caught by validation

    return result


def validate_mandatory_params(
    param_defs: list[PlanParamDef],
    provided_params: dict[str, str],
) -> list[str]:
    """Check that all mandatory params are provided. Returns list of missing param names."""
    missing = []
    for param_def in param_defs:
        if param_def.is_mandatory and param_def.name not in provided_params:
            missing.append(param_def.name)
    return missing


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
    """Import a skill plan from YAML file with global params section.

    The YAML can have:
    - goal: string
    - success_criteria: string
    - preparation_plan: string
    - params: list of "NAME" or "NAME:default" (NEW FORMAT)
    - plan: list of steps

    Global params are automatically resolved and will be injected into skills at runtime.
    Steps should NOT declare their own params (they are ignored if present).
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Plan file not found: {filepath}")

    raw_data = yaml.safe_load(path.read_text())
    if not isinstance(raw_data, dict):
        raise ValueError(f"Invalid plan YAML format in {filepath}")

    # Parse global params section (NEW FORMAT)
    raw_param_defs = raw_data.get("params", [])
    if raw_param_defs and not isinstance(raw_param_defs, list):
        raise ValueError(f"Invalid 'params' section in {filepath}. Expected a list of 'NAME' or 'NAME:default'")

    try:
        param_defs = parse_global_params(raw_param_defs)
    except ValueError as exc:
        raise ValueError(f"Invalid params section in {filepath}: {exc}") from exc

    # Build final params dict: global defaults + CLI overrides
    resolved_params = build_params_dict(param_defs, params)

    # Validate mandatory params are provided
    missing_mandatory = validate_mandatory_params(param_defs, resolved_params)
    if missing_mandatory:
        raise ValueError(
            f"Missing required plan parameters: {', '.join(missing_mandatory)}. "
            f"Provide values with -p/--param options."
        )

    # Also check for legacy per-skill params with {{}} placeholders and validate them
    # This is a transitional check - the new format doesn't use {{}} in steps
    raw_plan_data = raw_data.get("plan", [])
    legacy_placeholders = _find_legacy_placeholders_in_plan(raw_plan_data)
    if legacy_placeholders:
        missing_legacy = [p for p in legacy_placeholders if p not in resolved_params]
        if missing_legacy:
            raise ValueError(
                f"Unresolved placeholders in plan: {', '.join(set(missing_legacy))}. "
                f"Provide values with -p/--param options or add them to the global 'params:' section."
            )
        # If all legacy placeholders are resolved, still apply substitution for backward compat
        data = substitute_placeholders(dict(raw_data), resolved_params)
    else:
        # New format: no {{}} in steps, just use resolved_params directly
        data = dict(raw_data)
        # Still substitute {{}} in goal, success_criteria, etc. if present
        for key in ["goal", "success_criteria", "preparation_plan"]:
            if key in data and isinstance(data[key], str):
                data[key] = substitute_placeholders(data[key], resolved_params)

    goal = data.get("goal", "")
    if not goal:
        raise ValueError(f"Plan missing 'goal' field in {filepath}")

    plan_steps = []
    plan_data = data.get("plan", [])

    for i, step_dict in enumerate(plan_data, 1):
        action = step_dict.get("action", "")
        if action not in ("run", "task", "ask"):
            raise ValueError(f"Step {i} has invalid action: {action}")

        # Get original (pre-substitution) values
        raw_step = raw_plan_data[i - 1] if i - 1 < len(raw_plan_data) else {}
        original_desc = raw_step.get("description", "")

        step = SkillPlanStep(
            step=i,
            action=action,
            skill_name=step_dict.get("skill", ""),
            params={},  # Global params will be injected at runtime by the router
            original_params={},
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


def _find_legacy_placeholders_in_plan(plan_data: list) -> list[str]:
    """Find all {{key}} placeholders in the plan steps (legacy format)."""
    placeholders = []
    for step in plan_data:
        if isinstance(step, dict):
            _collect_placeholders(step, placeholders)
    return placeholders


def _collect_placeholders(obj: Any, result: list[str]) -> None:
    """Recursively collect all {{key}} and {{key:default}} placeholders."""
    if isinstance(obj, str):
        for m in re.finditer(r"\{\{([^}]+)\}\}", obj):
            inner = m.group(1)
            if ":" in inner:
                key = inner.split(":", 1)[0].strip()
            else:
                key = inner.strip()
            result.append(key)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_placeholders(v, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_placeholders(item, result)


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

        # Fallback: also search in workdir_root
        try:
            from common.core.config import load_common_config
            common_config = load_common_config()
            workdir_root = common_config.get("workdir_root")
            if workdir_root:
                workdir_root_path = Path(workdir_root).expanduser().resolve()
                if workdir_root_path.exists() and workdir_root_path.is_dir():
                    root_plans = self._find_run_plans(workdir_root_path)
                    for plan_path in root_plans:
                        try:
                            rel = plan_path.relative_to(workdir_root_path).as_posix()
                        except ValueError:
                            rel = str(plan_path)

                        if not rel.startswith(incomplete):
                            continue

                        # Avoid duplicates
                        if any(item.value == rel for item in items):
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
        except Exception:
            pass

        return items

    def convert(self, value, param, ctx):
        # If it's a relative path, resolve against workdir
        path = Path(value)
        if not path.is_absolute():
            workdir = self._get_workdir()
            path = workdir / path
            # Fallback to workdir_root if file not found in workdir
            if not path.exists():
                try:
                    from common.core.config import load_common_config
                    common_config = load_common_config()
                    workdir_root = common_config.get("workdir_root")
                    if workdir_root:
                        workdir_root_path = Path(workdir_root).expanduser().resolve()
                        fallback_path = workdir_root_path / value
                        if fallback_path.exists():
                            path = fallback_path
                except Exception:
                    pass
        return path.resolve()


# Keep backwards compatibility alias
_substitute_placeholders = substitute_placeholders
_find_missing_placeholders = find_missing_placeholders
_import_plan_from_yaml = import_plan_from_yaml
