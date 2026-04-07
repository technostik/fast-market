from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from common import structlog
from common.core.config import load_common_config, load_tool_config, save_tool_config
from common.core.yaml_utils import dump_yaml
from common.core.paths import get_skills_dir
from common.llm.registry import get_default_provider_name
from core.skill import Skill

logger = structlog.get_logger(__name__)


def _resolve_save_session_path(save_session: str | None, workdir: Path) -> Path | None:
    """Resolve save_session path relative to workdir if it's a relative path."""
    if not save_session:
        return None

    session_path = Path(save_session).expanduser()

    if session_path.is_absolute():
        return session_path.resolve()

    return (workdir / session_path).resolve()


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
    result: Any,
    provided_params: dict[str, str],
    workdir_path: Path | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> None:
    if not save_session:
        return

    if workdir_path is None:
        workdir_path = Path(".")

    session_path = _resolve_save_session_path(save_session, workdir_path)
    if session_path is None:
        return

    session_path.parent.mkdir(parents=True, exist_ok=True)

    skill_name = skill_ref.split("/", 1)[0]

    payload = {
        "task_description": f"skill apply {skill_ref}",
        "workdir": str(workdir_path) if workdir_path else ".",
        "provider": provider_name or "default",
        "model": model_name or "default",
        "max_iterations": 1,
        "task_params": provided_params,
        "exit_code": result.exit_code,
        "start_time": datetime.utcnow().isoformat(),
        "end_time": datetime.utcnow().isoformat(),
        "end_reason": "completed" if result.exit_code == 0 else "failed",
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
                "content": f"Executing skill: {skill_ref}",
                "timestamp": datetime.utcnow().isoformat(),
                "tool_calls": [
                    {
                        "tool_call_id": "skill-exec-1",
                        "tool_name": "skill_execute",
                        "arguments": {
                            "skill_ref": skill_ref,
                            "params": provided_params,
                        },
                        "exit_code": result.exit_code,
                        "stdout": result.stdout or "",
                        "stderr": result.stderr or "",
                    }
                ],
            }
        ],
    }
    session_path.write_text(
        dump_yaml(payload, sort_keys=False),
        encoding="utf-8",
    )


def apply_skill_impl(
    skill_ref: str,
    params: tuple[str, ...],
    workdir: str | None = None,
    timeout: int | None = None,
    max_iterations: int | None = None,
    llm_timeout: int | None = None,
    dry_run: bool = False,
    fmt: str = "text",
    provider: str | None = None,
    model: str | None = None,
    auto_learn: bool = False,
    save_session: str | None = None,
    compact: bool = False,
    verbose: bool = False,
    debug: str | None = None,
    isolated: bool = False,
    inject: str | None = None,
) -> None:
    from core.runner import (
        execute_skill_prompt,
        execute_skill_run,
        execute_skill_script,
        make_run_root,
        resolve_skill_script,
    )

    if workdir is None:
        common_config = load_common_config()
        workdir = common_config.get("workdir") or "."

    workdir_path = Path(workdir).expanduser().resolve()

    if isolated:
        skill_name_for_dir = skill_ref.split("/", 1)[0]
        workdir_path = make_run_root(workdir_path, skill_name_for_dir)

    if fmt != "json":
        click.echo(f"workdir: {workdir_path}")

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
        if (
            p.get("required")
            and p["name"] not in provided_params
            and "default" not in p
        ):
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
            click.echo(
                f"[DRY RUN] Script: {script_path if script_path else '(unresolved)'}"
            )
            return

        result = execute_skill_script(
            skill_ref=skill_ref,
            workdir=workdir_path,
            params=provided_params or None,
        )
        _write_local_session_file(
            save_session,
            skill_ref,
            result,
            provided_params,
            workdir_path=workdir_path,
            provider_name=None,
            model_name=None,
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
        )
        _write_local_session_file(
            save_session,
            skill_ref,
            result,
            provided_params,
            workdir_path=workdir_path,
            provider_name=None,
            model_name=None,
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

        llm_display = model_name if model_name else "default"
        if provider_name:
            llm_display = f"{provider_name}/{llm_display}"
        click.echo(f"llm: {llm_display}")

        if dry_run:
            if fmt == "json":
                click.echo(json.dumps({"exit_code": 0, "stdout": "", "stderr": ""}))
                return
            click.echo("[DRY RUN] Mode: prompt (via task apply)")
            if provider_name:
                click.echo(f"[DRY RUN] Provider: {provider_name}")
            if model_name:
                click.echo(f"[DRY RUN] Model: {model_name}")
            if inject:
                click.echo("[DRY RUN] Injected instructions:")
                inject_preview = inject[:200] + ("..." if len(inject) > 200 else "")
                click.echo(f"  {inject_preview}")
            click.echo("[DRY RUN] Task description:")
            preview = body[:200] + ("..." if len(body) > 200 else "")
            click.echo(f"  {preview}")
            return

        auto_learn_session_path = None
        if auto_learn and not save_session:
            auto_learn_session_path = workdir_path / ".auto_learn.session.yaml"

        resolved_save_session = (
            _resolve_save_session_path(save_session, workdir_path)
            or auto_learn_session_path
        )

        result = execute_skill_prompt(
            skill=skill,
            workdir=workdir_path,
            params=provided_params or None,
            timeout=timeout,
            max_iterations=max_iterations,
            llm_timeout=llm_timeout,
            auto_learn=False,  # Handle auto-learn in skill-cli after task completes
            provider=provider_name,
            model=model_name,
            save_session=resolved_save_session,
            compact=compact,
            verbose=verbose,
            debug=debug,
            inject=inject,
        )

        if auto_learn:
            from core.runner import _run_auto_learn_from_skill

            timed_out_seconds = timeout if timeout is not None else skill.timeout
            if timed_out_seconds is None:
                timed_out_seconds = 300
            timed_out_seconds = int(str(timed_out_seconds).rstrip("s"))

            session = None
            session_path = auto_learn_session_path or _resolve_save_session_path(
                save_session, workdir_path
            )
            if session_path and session_path.exists():
                import yaml

                session_data = yaml.safe_load(session_path.read_text())
                if session_data:
                    from common.agent.session import Session

                    session = Session.from_dict(session_data)

            llm_provider = None
            if provider_name:
                try:
                    from common.core.config import (
                        requires_common_config,
                        load_tool_config,
                    )
                    from common.llm.registry import (
                        discover_providers,
                        get_default_provider_name,
                    )

                    requires_common_config("skill", ["llm"])
                    config = load_tool_config("skill")
                    providers = discover_providers(config)
                    llm_provider = providers.get(provider_name)
                except Exception as e:
                    logger.warning("auto_learn_llm_provider_failed", error=str(e))

            _run_auto_learn_from_skill(
                skill=skill,
                params=provided_params,
                workdir=workdir_path,
                timed_out=result.timed_out,
                timed_out_seconds=timed_out_seconds,
                provider=llm_provider,
                model=model_name,
                session=session,
                session_path=session_path,
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
