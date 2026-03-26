from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from common.core.config import load_tool_config
from core.executor import execute_action
from core.models import ItemMetadata, RuleMismatchLog, TriggerLog
from core.rule_engine import evaluate_rule_with_details
from core.time_scheduler import should_run_rule

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def _get_global_on_error_action_ids() -> list[str]:
    """Get global on_error_action_ids from monitor config."""
    try:
        config = load_tool_config("monitor")
        return config.get("global_on_error_action_ids", [])
    except Exception:
        return []


def _get_global_on_execution_action_ids() -> list[str]:
    """Get global on_execution_action_ids from monitor config."""
    try:
        config = load_tool_config("monitor")
        return config.get("global_on_execution_action_ids", [])
    except Exception:
        return []


def _get_default_check_interval() -> str | None:
    """Get default_check_interval from monitor config."""
    try:
        config = load_tool_config("monitor")
        return config.get("default_check_interval")
    except Exception:
        return None


def _build_hook_item_metadata(
    item: ItemMetadata, rule_id: str, rule_msg: str, content_type: str
) -> ItemMetadata:
    """Build synthetic ItemMetadata for on_error/on_execution hooks."""
    return ItemMetadata(
        id=rule_id,
        title=rule_msg,
        url=item.url,
        published_at=item.published_at,
        content_type=content_type,
        source_plugin=item.source_plugin,
        source_id=item.source_id,
        extra={},
    )


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.option("--cron", is_flag=True, help="Run in cron mode (no output unless errors)")
    @click.option("--source-id", help="Run only for specific source")
    @click.option("--dry-run", is_flag=True, help="Evaluate rules without executing actions")
    @click.option(
        "--force",
        is_flag=True,
        help="Ignore cooldown, process all available items (for testing)",
    )
    @click.option(
        "--limit", type=int, default=50, help="Max items to process per source (default: 50)"
    )
    @click.option(
        "--silent",
        is_flag=True,
        help="Suppress replay of command output (action results will still be logged)",
    )
    @click.option(
        "--ignore-enabled",
        is_flag=True,
        help="Execute disabled actions and rules (for testing)",
    )
    @click.option("--debug", is_flag=True, help="Show detailed trigger info")
    @click.option("--format", "fmt", type=click.Choice(["json", "text", "yaml"]), default="text")
    @click.option(
        "--workdir",
        "-w",
        default=None,
        help="Working directory for action execution (default: from config)",
    )
    @click.pass_context
    def run_cmd(
        ctx, cron, source_id, dry_run, force, limit, silent, ignore_enabled, debug, fmt, workdir
    ):
        storage = get_storage()

        sources = storage.get_all_sources(include_disabled=ignore_enabled)
        if source_id:
            sources = [s for s in sources if s.id == source_id]

        if not sources:
            if not cron:
                out_formatted(
                    {"error": "No sources found. Run 'monitor setup source-add' first."},
                    fmt,
                )
            return

        config = {}
        resolved_workdir = None
        if workdir:
            resolved_workdir = Path(workdir).expanduser().resolve()
        else:
            try:
                common_config = load_tool_config("monitor")
                workdir_path = common_config.get("workdir")
                if workdir_path:
                    resolved_workdir = Path(workdir_path).expanduser().resolve()
            except Exception:
                pass

        rules = storage.get_all_rules(include_disabled=ignore_enabled)
        if not rules:
            if not cron:
                out_formatted(
                    {"error": "No rules found. Run 'monitor setup rule-add' first."},
                    fmt,
                )
            return

        triggered = []
        mismatches = []
        errors = []
        source_stats = {}
        total_actions_executed = 0
        total_actions_skipped = 0
        total_actions_failed = 0
        total_sources_skipped = 0

        for source in sources:
            source_origin_str = source.origin
            if len(source_origin_str) > 40:
                source_origin_str = source_origin_str[:37] + "..."

            if source.plugin not in plugin_manifests:
                error_msg = f"Plugin '{source.plugin}' not found for source '{source.id}'"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)
                continue

            plugin_cls = plugin_manifests[source.plugin].source_plugin_class
            default_check_interval = _get_default_check_interval()
            effective_check_interval = source.check_interval or default_check_interval
            plugin_metadata = {**source.metadata}
            if effective_check_interval:
                plugin_metadata["check_interval"] = effective_check_interval
            plugin_instance = plugin_cls(
                config,
                {
                    "id": source.id,
                    "origin": source.origin,
                    "metadata": plugin_metadata,
                    "last_check": source.last_check,
                    "check_interval": effective_check_interval,
                },
            )

            force_mode = force or (not source.is_new)
            cooldown_active = not plugin_instance._should_fetch()
            items = []
            fetch_error = None

            try:
                if cooldown_active:
                    interval_display, remaining = _get_cooldown_remaining(
                        plugin_instance, effective_check_interval
                    )
                    if force_mode:
                        if not cron:
                            click.echo(
                                f"⚠️  FORCE: Bypassing cooldown for source='{source.id}' "
                                f"(interval: {interval_display}, remaining: {remaining})",
                                err=True,
                            )
                    else:
                        if not cron:
                            click.echo(
                                f"[COOLDOWN] source='{source.id}' - "
                                f"skipped (interval: {interval_display}, remaining: {remaining})",
                                err=True,
                            )
                        source_stats[source.id] = {
                            "fetched": 0,
                            "filtered": 0,
                            "skipped": "cooldown",
                        }
                        total_sources_skipped += 1
                        continue

                force_mode = force or (not source.is_new)
                if force_mode:
                    if not cron:
                        click.echo(
                            f"⚡  FORCE: source='{source.id}' processing up to {limit} items",
                            err=True,
                        )
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(last_item_id=None, limit=limit, force=True)
                    )
                else:
                    items = asyncio.run(
                        plugin_instance.fetch_new_items(
                            last_item_id=source.last_item_id,
                            limit=limit,
                        )
                    )
            except Exception as e:
                fetch_error = str(e)
                error_msg = f"Fetch failed for source='{source.id}': {fetch_error}"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)

            if fetch_error:
                source_stats[source.id] = {"fetched": 0, "filtered": 0, "error": fetch_error}
                continue

            fetched_count = len(items)

            if items and not force_mode:
                newest_item = max(items, key=lambda x: x.published_at)
                source.last_fetched_at = newest_item.published_at
                source.last_item_id = newest_item.id
                storage.update_source_last_fetched_at(source.id, source.last_fetched_at)
                storage.update_source_last_item_id(source.id, source.last_item_id)
            elif not items and not force_mode and not source.last_item_id:
                if not cron:
                    click.echo(
                        f"⚠️  source='{source.id}' first run: fetched 0 items. "
                        f"Next run will fetch more (last_item_id will be set).",
                        err=True,
                    )

            if not force_mode:
                now = datetime.now(timezone.utc)
                source.last_check = now
                storage.update_source_last_check_time(source.id, now)

            matched_items = []
            for item in items:
                for rule in rules:
                    try:
                        if not should_run_rule(rule):
                            continue
                        result = evaluate_rule_with_details(rule, item, source)
                        if result.matched:
                            triggered.append({"rule": rule, "item": item, "source": source})
                            matched_items.append(item.id)
                        elif debug and source.enabled and rule.enabled:
                            evaluated_at = datetime.now(timezone.utc)
                            mismatches.append(
                                {
                                    "rule": rule,
                                    "item": item,
                                    "source": source,
                                    "failed_conditions": result.failed_conditions,
                                    "evaluated_at": evaluated_at,
                                }
                            )
                            click.echo(
                                f"[NO_MATCH] rule='{rule.id}' item='{item.title}' "
                                f"failed={len(result.failed_conditions)}",
                                err=True,
                            )
                            for fc in result.failed_conditions:
                                reason = fc.get("reason", "unknown")
                                click.echo(
                                    f"  - {fc['field']} {fc['operator']} {fc.get('expected')!r}: {reason}",
                                    err=True,
                                )
                    except Exception as e:
                        error_msg = f"Rule evaluation error for '{rule.id}': {str(e)}"
                        errors.append(error_msg)
                        click.echo(f"[ERROR] {error_msg}", err=True)

            filtered_count = fetched_count - len(set(matched_items))

            source_stats[source.id] = {
                "fetched": fetched_count,
                "matched": len(matched_items),
                "filtered": filtered_count,
            }

            if not cron and not silent:
                if fetched_count == 0:
                    is_new_note = " (is_new mode)" if source.is_new else ""
                    checked_note = f", {source.last_item_id} known" if source.last_item_id else ""
                    checked = 1 if source.last_item_id else 0
                    click.echo(
                        f"  → source='{source.id}' checked={checked}, new=0{checked_note}{is_new_note}",
                        err=True,
                    )
                else:
                    is_new_note = " (is_new mode)" if source.is_new else ""
                    click.echo(
                        f"  → source='{source.id}' checked={fetched_count}, "
                        f"new={len(matched_items)}, filtered={filtered_count}{is_new_note}",
                        err=True,
                    )

            if force and items:
                if not cron:
                    click.echo(
                        "  → Force mode: NOT updating last_fetched_at or last_check",
                        err=True,
                    )

        for mismatch in mismatches:
            rule = mismatch["rule"]
            item = mismatch["item"]
            source = mismatch["source"]
            evaluated_at = mismatch["evaluated_at"]
            storage.log_rule_mismatch(
                RuleMismatchLog(
                    id=str(uuid.uuid4()),
                    rule_id=rule.id,
                    source_id=source.id,
                    item_id=item.id,
                    item_title=item.title,
                    failed_conditions=mismatch["failed_conditions"],
                    evaluated_at=evaluated_at,
                )
            )

        for entry in triggered:
            rule = entry["rule"]
            item = entry["item"]
            source = entry["source"]

            triggered_at = datetime.now(timezone.utc)
            if not dry_run:
                action_results = []
                actions_executed = 0
                actions_skipped = 0
                actions_failed = 0

                for action_id in rule.action_ids:
                    action = storage.get_action(action_id)
                    if not action:
                        error_msg = f"Action '{action_id}' not found in storage"
                        errors.append(error_msg)
                        click.echo(f"[ERROR] {error_msg}", err=True)
                        actions_skipped += 1
                        continue
                    if not ignore_enabled and not action.enabled:
                        error_msg = f"Action '{action_id}' is disabled, skipping (use --ignore-enabled to force execution)"
                        errors.append(error_msg)
                        actions_skipped += 1
                        continue
                    try:
                        code, output, script_content = execute_action(
                            action, item, source, rule.id, workdir=resolved_workdir
                        )
                        actions_executed += 1

                        action_results.append(
                            {
                                "action_id": action_id,
                                "exit_code": code,
                                "output": output,
                            }
                        )

                        storage.log_trigger(
                            TriggerLog(
                                id=str(uuid.uuid4()),
                                rule_id=rule.id,
                                source_id=source.id,
                                action_id=action.id,
                                item_id=item.id,
                                item_title=item.title,
                                item_url=item.url,
                                item_extra=item.extra,
                                triggered_at=triggered_at,
                                exit_code=code,
                                output=output,
                            )
                        )

                        storage.update_rule_last_triggered_at(rule.id, triggered_at)

                        action.last_run = triggered_at
                        action.last_output = output
                        action.last_exit_code = code
                        storage.update_action(action)

                        if code != 0:
                            error_msg = f"Action '{action.id}' failed with exit code {code}\n--- Script ---\n{script_content}\n---"
                            errors.append(error_msg)
                            click.echo(f"[ERROR] {error_msg}", err=True)
                            total_actions_failed += 1
                        elif not silent and not cron:
                            click.echo(f"[{action.id}] exit={code}")
                            if output and debug:
                                click.echo(output)
                    except Exception as e:
                        error_msg = f"Action execution error for '{action.id}': {str(e)}"
                        errors.append(error_msg)
                        click.echo(f"[ERROR] {error_msg}", err=True)
                        total_actions_failed += 1
                        action_results.append(
                            {
                                "action_id": action_id,
                                "exit_code": -1,
                                "output": str(e),
                            }
                        )

                total_actions_executed += actions_executed
                total_actions_skipped += actions_skipped
                total_actions_failed += actions_failed

                global_on_error_action_ids = _get_global_on_error_action_ids()
                global_on_execution_action_ids = _get_global_on_execution_action_ids()

                for action_result in action_results:
                    code = action_result["exit_code"]
                    rule_error_msg = (
                        f"Action '{action_result['action_id']}' failed with exit code {code}"
                        if code != 0
                        else ""
                    )
                    error_context: dict[str, Any] = {
                        "rule_error": rule_error_msg,
                        "rule_result": f"exit={code}",
                        "rule_msg": f"Error: {rule_error_msg}"
                        if code != 0
                        else f"Result: exit={code}",
                    }

                    rule_time = datetime.now(timezone.utc).isoformat()
                    error_context["rule_time"] = rule_time

                    if code != 0:
                        on_error_executed = False

                        for on_error_action_id in rule.on_error_action_ids:
                            on_error_action = storage.get_action(on_error_action_id)
                            if on_error_action and (ignore_enabled or on_error_action.enabled):
                                try:
                                    if not silent and not cron:
                                        click.echo(
                                            f"[ON_ERROR/{on_error_action.id}] triggered for rule '{rule.id}'"
                                        )
                                    hook_item = _build_hook_item_metadata(
                                        item, rule.id, error_context["rule_msg"], "rule-error"
                                    )
                                    err_code, err_output, _ = execute_action(
                                        on_error_action,
                                        hook_item,
                                        source,
                                        rule.id,
                                        error_context=error_context,
                                        workdir=resolved_workdir,
                                    )
                                    on_error_executed = True
                                    if not silent and not cron:
                                        click.echo(
                                            f"[ON_ERROR/{on_error_action.id}] exit={err_code}"
                                        )
                                        if err_output:
                                            click.echo(err_output)
                                except Exception as e:
                                    error_msg = (
                                        f"ON_ERROR action '{on_error_action_id}' failed: {str(e)}"
                                    )
                                    errors.append(error_msg)
                                    click.echo(f"[ERROR] {error_msg}", err=True)

                        if not on_error_executed or not rule.on_error_action_ids:
                            for global_on_error_action_id in global_on_error_action_ids:
                                global_action = storage.get_action(global_on_error_action_id)
                                if global_action and (ignore_enabled or global_action.enabled):
                                    try:
                                        if not silent and not cron:
                                            click.echo(
                                                f"[GLOBAL_ON_ERROR/{global_action.id}] triggered for rule '{rule.id}'"
                                            )
                                        hook_item = _build_hook_item_metadata(
                                            item, rule.id, error_context["rule_msg"], "rule-error"
                                        )
                                        err_code, err_output, _ = execute_action(
                                            global_action,
                                            hook_item,
                                            source,
                                            rule.id,
                                            error_context=error_context,
                                            workdir=resolved_workdir,
                                        )
                                        if not silent and not cron:
                                            click.echo(
                                                f"[GLOBAL_ON_ERROR/{global_action.id}] exit={err_code}"
                                            )
                                            if err_output:
                                                click.echo(err_output)
                                    except Exception as e:
                                        error_msg = f"GLOBAL_ON_ERROR action '{global_on_error_action_id}' failed: {str(e)}"
                                        errors.append(error_msg)
                                        click.echo(f"[ERROR] {error_msg}", err=True)
                    else:
                        on_exec_executed = False

                        for on_exec_action_id in rule.on_execution_action_ids:
                            on_exec_action = storage.get_action(on_exec_action_id)
                            if on_exec_action and (ignore_enabled or on_exec_action.enabled):
                                try:
                                    if not silent and not cron:
                                        click.echo(
                                            f"[ON_EXEC/{on_exec_action.id}] triggered for rule '{rule.id}'"
                                        )
                                    hook_item = _build_hook_item_metadata(
                                        item, rule.id, error_context["rule_msg"], "rule-execution"
                                    )
                                    exec_code, exec_output, _ = execute_action(
                                        on_exec_action,
                                        hook_item,
                                        source,
                                        rule.id,
                                        error_context=error_context,
                                        workdir=resolved_workdir,
                                    )
                                    on_exec_executed = True
                                    if not silent and not cron:
                                        click.echo(
                                            f"[ON_EXEC/{on_exec_action.id}] exit={exec_code}"
                                        )
                                        if exec_output:
                                            click.echo(exec_output)
                                except Exception as e:
                                    error_msg = (
                                        f"ON_EXEC action '{on_exec_action_id}' failed: {str(e)}"
                                    )
                                    errors.append(error_msg)

                        if not on_exec_executed or not rule.on_execution_action_ids:
                            for global_on_exec_action_id in global_on_execution_action_ids:
                                global_action = storage.get_action(global_on_exec_action_id)
                                if global_action and (ignore_enabled or global_action.enabled):
                                    try:
                                        if not silent and not cron:
                                            click.echo(
                                                f"[GLOBAL_ON_EXEC/{global_action.id}] triggered for rule '{rule.id}'"
                                            )
                                        hook_item = _build_hook_item_metadata(
                                            item,
                                            rule.id,
                                            error_context["rule_msg"],
                                            "rule-execution",
                                        )
                                        exec_code, exec_output, _ = execute_action(
                                            global_action,
                                            hook_item,
                                            source,
                                            rule.id,
                                            error_context=error_context,
                                            workdir=resolved_workdir,
                                        )
                                        if not silent and not cron:
                                            click.echo(
                                                f"[GLOBAL_ON_EXEC/{global_action.id}] exit={exec_code}"
                                            )
                                            if exec_output:
                                                click.echo(exec_output)
                                    except Exception as e:
                                        error_msg = f"GLOBAL_ON_EXEC action '{global_on_exec_action_id}' failed: {str(e)}"
                                        errors.append(error_msg)
                                    click.echo(f"[ERROR] {error_msg}", err=True)

        if not cron:
            result = {
                "mode": "force" if force else "normal",
                "checked_sources": len(sources),
                "sources_skipped": total_sources_skipped,
                "triggered_rules": len(triggered),
                "actions_executed": total_actions_executed,
                "actions_skipped": total_actions_skipped,
                "actions_failed": total_actions_failed,
                "mismatches": len(mismatches),
                "limit_per_source": limit,
                "errors": errors,
                "source_stats": source_stats,
            }
            if debug:
                result["triggers"] = [
                    {
                        "rule_id": r["rule"].id,
                        "source_id": r["source"].id,
                        "item_id": r["item"].id,
                        "item_title": r["item"].title,
                    }
                    for r in triggered
                ]
            out_formatted(result, fmt)

        if errors and cron:
            for error in errors:
                click.echo(f"[ERROR] {error}", err=True)

    return CommandManifest(
        name="run",
        click_command=run_cmd,
    )


def _get_cooldown_remaining(
    plugin_instance, check_interval: str | int | None = None
) -> tuple[str, str]:
    """Returns (interval_display, remaining_time)"""
    interval_val = check_interval or plugin_instance.check_interval
    if not interval_val:
        return ("none", "none")

    # Handle integer directly
    if isinstance(interval_val, int):
        interval_seconds = interval_val
        interval_display = f"{interval_val}s"
    else:
        from core.time_scheduler import parse_interval

        try:
            interval_seconds = int(parse_interval(interval_val).total_seconds())
            interval_display = interval_val
        except (ValueError, TypeError):
            return ("invalid", "invalid")

    if plugin_instance.last_check is None:
        return (interval_display, "never checked")

    now = datetime.now(timezone.utc)

    if isinstance(plugin_instance.last_check, str):
        last_check_dt = datetime.fromisoformat(plugin_instance.last_check)
        if last_check_dt.tzinfo is None:
            last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
    else:
        last_check_dt = plugin_instance.last_check

    elapsed = (now - last_check_dt).total_seconds()
    remaining = interval_seconds - elapsed

    if remaining <= 0:
        return (interval_display, "0s")
    if remaining < 60:
        remaining_str = f"{int(remaining)}s"
    elif remaining < 3600:
        remaining_str = f"{int(remaining / 60)}m"
    else:
        remaining_str = f"{int(remaining / 3600)}h"

    return (interval_display, remaining_str)
