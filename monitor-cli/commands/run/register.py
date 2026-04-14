from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from common.core.config import load_tool_config
from core.executor import execute_action
from core.models import Action, ItemMetadata, Rule, RuleMismatchLog, Source, TriggerLog
from core.rule_engine import evaluate_rule_with_details
from core.time_scheduler import should_run_rule

_TOOL_ROOT = Path(__file__).resolve().parents[2]


def _get_global_on_error_action_ids() -> list[str]:
    try:
        config = load_tool_config("monitor")
        return config.get("global_on_error_action_ids", [])
    except Exception:
        return []


def _get_global_on_execution_action_ids() -> list[str]:
    try:
        config = load_tool_config("monitor")
        return config.get("global_on_execution_action_ids", [])
    except Exception:
        return []


def _get_default_slowdown() -> str | None:
    try:
        config = load_tool_config("monitor")
        return config.get("default_slowdown")
    except Exception:
        return None


def _get_seen_items_decay_days() -> int:
    try:
        config = load_tool_config("monitor")
        return config.get("seen_items_decay_days", 30)
    except Exception:
        return 30


def _get_triggered_items_decay_days() -> int:
    try:
        config = load_tool_config("monitor")
        return config.get("triggered_items_decay_days", 7)
    except Exception:
        return 7


def _build_hook_item_metadata(
    item: ItemMetadata, rule_id: str, rule_msg: str, content_type: str
) -> ItemMetadata:
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


def _cleanup_old_triggered_items(storage, rules, now, cron):
    triggered_decay_days = _get_triggered_items_decay_days()
    if triggered_decay_days > 0:
        cutoff = now - timedelta(days=triggered_decay_days)
        for rule in rules:
            removed = storage.clean_old_triggered_items(rule.id, cutoff)
            if removed > 0 and not cron:
                click.echo(
                    f"[CLEANUP] rule='{rule.id}' removed {removed} expired triggered items",
                    err=True,
                )


def _cleanup_old_seen_items(storage, source, now, cron):
    decay_days = _get_seen_items_decay_days()
    if decay_days > 0:
        cutoff = now - timedelta(days=decay_days)
        removed = storage.clean_old_seen_items(source.id, cutoff)
        if removed > 0 and not cron:
            click.echo(
                f"[CLEANUP] source='{source.id}' removed {removed} expired seen items",
                err=True,
            )


def _get_cooldown_info(plugin_instance, slowdown):
    interval_val = slowdown or plugin_instance.slowdown
    if not interval_val:
        return None

    if isinstance(interval_val, int):
        interval_seconds = interval_val
        interval_display = f"{interval_val}s"
    else:
        from core.time_scheduler import parse_interval

        try:
            interval_seconds = int(parse_interval(interval_val).total_seconds())
            interval_display = interval_val
        except (ValueError, TypeError):
            return None

    if plugin_instance.last_check is None:
        return {"display": interval_display, "remaining": "never checked", "active": True}

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
        return {"display": interval_display, "remaining": "0s", "active": False}

    if remaining < 60:
        remaining_str = f"{int(remaining)}s"
    elif remaining < 3600:
        remaining_str = f"{int(remaining / 60)}m"
    else:
        remaining_str = f"{int(remaining / 3600)}h"

    return {"display": interval_display, "remaining": remaining_str, "active": True}


def _fetch_items_for_source(source, plugin_cls, config, limit, force, cron, storage):
    import time

    plugin_metadata = {**source.metadata}
    if source.slowdown:
        plugin_metadata["slowdown"] = source.slowdown

    plugin_instance = plugin_cls(
        config,
        {
            "id": source.id,
            "origin": source.origin,
            "metadata": plugin_metadata,
            "last_check": source.last_check,
            "slowdown": source.slowdown,
        },
    )

    cooldown_info = _get_cooldown_info(plugin_instance, source.slowdown)
    force_mode = force or (not source.is_new)

    should_skip = cooldown_info and cooldown_info["active"] and not force_mode

    if should_skip:
        if not cron:
            click.echo(
                f"[COOLDOWN] source='{source.id}' - "
                f"skipped (interval: {cooldown_info['display']}, remaining: {cooldown_info['remaining']})",
                err=True,
            )
        return {
            "skipped": "cooldown",
            "cooldown": cooldown_info,
            "items": [],
            "plugin": plugin_instance,
        }

    if not cron:
        click.echo(
            f"📥 Fetching source='{source.id}' plugin={source.plugin} limit={limit}", err=True
        )

    seen_item_ids = None if force_mode else storage.get_seen_item_ids(source.id)
    if seen_item_ids and not cron:
        sample = list(seen_item_ids)[:3]
        click.echo(f"  seen_item_ids={len(seen_item_ids)} (sample: {sample})", err=True)

    fetch_start = time.time()
    try:
        if force_mode:
            items = asyncio.run(
                plugin_instance.fetch_new_items(
                    last_item_id=None,
                    limit=limit,
                    force=True,
                )
            )
        else:
            items = asyncio.run(
                plugin_instance.fetch_new_items(
                    last_item_id=source.last_item_id,
                    limit=limit,
                    seen_item_ids=seen_item_ids,
                )
            )
    except Exception as e:
        if not cron:
            click.echo(f"[ERROR] Fetch failed for source='{source.id}': {e}", err=True)
        return {"error": str(e), "items": [], "plugin": plugin_instance}

    fetch_time = time.time() - fetch_start
    if not cron:
        click.echo(f"  → fetched {len(items)} items in {fetch_time:.1f}s", err=True)

    return {
        "items": items,
        "plugin": plugin_instance,
        "plugin_metadata": plugin_instance.metadata,
        "cooldown": cooldown_info,
        "raw_fetched_count": len(items),
        "fetch_time": fetch_time,
    }


def _filter_by_seen(items, source, storage, force_mode):
    if force_mode or not source.is_new:
        return items, 0

    seen_ids = storage.get_seen_item_ids(source.id)
    if not seen_ids:
        return items, 0

    original_count = len(items)
    filtered = [item for item in items if item.id not in seen_ids]
    filtered_count = original_count - len(filtered)
    return filtered, filtered_count


def _filter_by_last_item_id(items, source, force_mode):
    if force_mode or not source.last_item_id or source.plugin == "channel_list":
        return items, 0

    original_count = len(items)
    filtered = []
    for item in items:
        if item.id == source.last_item_id:
            break
        filtered.append(item)

    filtered_count = original_count - len(filtered)
    return filtered, filtered_count


def _evaluate_and_match(items, source, rules, storage, force_mode, cron, debug):
    triggered = []
    mismatches = []
    matched_item_ids = []

    triggered_by_rule = {rule.id: storage.get_triggered_item_ids(rule.id) for rule in rules}

    for item in items:
        for rule in rules:
            if not should_run_rule(rule):
                continue

            if not force_mode and item.id in triggered_by_rule.get(rule.id, set()):
                continue

            result = evaluate_rule_with_details(rule, item, source)

            if result.matched:
                triggered.append({"rule": rule, "item": item, "source": source})
                matched_item_ids.append(item.id)
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
                if not cron:
                    click.echo(
                        f"[NO_MATCH] rule='{rule.id}' item='{item.title[:40]}' "
                        f"failed={len(result.failed_conditions)}",
                        err=True,
                    )
                    for fc in result.failed_conditions:
                        reason = fc.get("reason", "unknown")
                        click.echo(
                            f"  - {fc['field']} {fc['operator']} {fc.get('expected')!r}: {reason}",
                            err=True,
                        )

    matched_ids_set = set(matched_item_ids)
    return triggered, mismatches, matched_ids_set


def _update_source_tracking(source, storage, items, force_mode, plugin_instance=None):
    if force_mode or not items:
        return

    now = datetime.now(timezone.utc)
    source.last_check = now

    newest_item = max(items, key=lambda x: x.published_at)
    source.last_fetched_at = newest_item.published_at

    if source.plugin == "channel_list":
        channel_last_ids = source.metadata.get("last_item_ids_by_channel", {})
        if channel_last_ids:
            source.last_item_id = newest_item.id
            storage.update_source_metadata(source.id, source.metadata)
    else:
        source.last_item_id = newest_item.id

    storage.update_source_last_check_time(source.id, now)
    storage.update_source_last_fetched_at(source.id, source.last_fetched_at)
    storage.update_source_last_item_id(source.id, source.last_item_id)


def _mark_seen_items(storage, source, items, force_mode):
    if force_mode or not items or not source.is_new:
        return

    items_to_mark = [(item.id, item.published_at) for item in items]
    storage.add_seen_items(source.id, items_to_mark)


def _execute_actions_for_trigger(
    storage,
    rule,
    item,
    source,
    triggered_at,
    resolved_workdir,
    force_mode,
    ignore_enabled,
    dry_run,
    silent,
    cron,
    errors,
    total_actions,
):
    action_results = []
    (actions_executed, actions_skipped, actions_failed) = total_actions

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
            click.echo(f"[ERROR] {error_msg}", err=True)
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

            if not force_mode and source.is_new:
                storage.add_triggered_item(rule.id, item.id)

            storage.update_rule_last_triggered_at(rule.id, triggered_at)

            action.last_run = triggered_at
            action.last_output = output
            action.last_exit_code = code
            storage.update_action(action)

            if code != 0:
                error_msg = f"Action '{action.id}' failed with exit code {code}\n--- Script ---\n{script_content}\n---"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)
                actions_failed += 1
            elif not silent and not cron:
                click.echo(f"[{action.id}] exit={code}")
                if output:
                    click.echo(output)

        except Exception as e:
            error_msg = f"Action execution error for '{action.id}': {str(e)}"
            errors.append(error_msg)
            click.echo(f"[ERROR] {error_msg}", err=True)
            actions_failed += 1
            action_results.append(
                {
                    "action_id": action_id,
                    "exit_code": -1,
                    "output": str(e),
                }
            )

    return action_results, actions_executed, actions_skipped, actions_failed


def _handle_global_hooks(
    action_results,
    rule,
    errors,
    storage,
    resolved_workdir,
    global_on_error_action_ids,
    global_on_execution_action_ids,
    item,
    source,
    item_title,
    silent,
    cron,
    ignore_enabled,
):
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
            "rule_msg": f"Error: {rule_error_msg}" if code != 0 else f"Result: exit={code}",
        }
        rule_time = datetime.now(timezone.utc).isoformat()
        error_context["rule_time"] = rule_time

        if code != 0:
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
                        if not silent and not cron:
                            click.echo(f"[ON_ERROR/{on_error_action.id}] exit={err_code}")
                            if err_output:
                                click.echo(err_output)
                    except Exception as e:
                        error_msg = f"ON_ERROR action '{on_error_action_id}' failed: {str(e)}"
                        errors.append(error_msg)
                        click.echo(f"[ERROR] {error_msg}", err=True)

            if not rule.on_error_action_ids:
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
                                click.echo(f"[GLOBAL_ON_ERROR/{global_action.id}] exit={err_code}")
                                if err_output:
                                    click.echo(err_output)
                        except Exception as e:
                            error_msg = f"GLOBAL_ON_ERROR action '{global_on_error_action_id}' failed: {str(e)}"
                            errors.append(error_msg)
                            click.echo(f"[ERROR] {error_msg}", err=True)
        else:
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
                        if not silent and not cron:
                            click.echo(f"[ON_EXEC/{on_exec_action.id}] exit={exec_code}")
                            if exec_output:
                                click.echo(exec_output)
                    except Exception as e:
                        error_msg = f"ON_EXEC action '{on_exec_action_id}' failed: {str(e)}"
                        errors.append(error_msg)

            if not rule.on_execution_action_ids:
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
                                click.echo(f"[GLOBAL_ON_EXEC/{global_action.id}] exit={exec_code}")
                                if exec_output:
                                    click.echo(exec_output)
                        except Exception as e:
                            error_msg = f"GLOBAL_ON_EXEC action '{global_on_exec_action_id}' failed: {str(e)}"
                            errors.append(error_msg)
                            click.echo(f"[ERROR] {error_msg}", err=True)


def _display_source_summary(
    source,
    raw_fetched_count,
    fetched_count,
    seen_filtered_count,
    lastid_filtered_count,
    triggered_filtered_count,
    matched_count,
    is_new,
    cron,
    silent,
):
    if cron or silent:
        return

    is_new_note = " (is_new mode)" if is_new else ""

    if fetched_count == 0:
        checked_note = f", {source.last_item_id} known" if source.last_item_id else ""
        click.echo(
            f"  → source='{source.id}' checked={fetched_count}, new=0{checked_note}{is_new_note}",
            err=True,
        )
    else:
        detail_parts = []
        if seen_filtered_count > 0:
            detail_parts.append(f"seen={seen_filtered_count}")
        if lastid_filtered_count > 0:
            detail_parts.append(f"by_id={lastid_filtered_count}")
        if triggered_filtered_count > 0:
            detail_parts.append(f"triggered={triggered_filtered_count}")
        detail_str = f" ({', '.join(detail_parts)})" if detail_parts else ""
        click.echo(
            f"  → source='{source.id}' fetched={raw_fetched_count}, "
            f"checked={fetched_count}, new={matched_count}{detail_str}{is_new_note}",
            err=True,
        )


def _log_mismatches(storage, mismatches):
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
        now = datetime.now(timezone.utc)

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

        _cleanup_old_triggered_items(storage, rules, now, cron)

        triggered = []
        mismatches = []
        errors = []
        source_stats = {}
        total_actions_executed = 0
        total_actions_skipped = 0
        total_actions_failed = 0
        total_sources_skipped = 0

        for source in sources:
            if source.plugin not in plugin_manifests:
                error_msg = f"Plugin '{source.plugin}' not found for source '{source.id}'"
                errors.append(error_msg)
                click.echo(f"[ERROR] {error_msg}", err=True)
                continue

            _cleanup_old_seen_items(storage, source, now, cron)

            plugin_cls = plugin_manifests[source.plugin].source_plugin_class
            force_mode = force or (not source.is_new)

            fetch_result = _fetch_items_for_source(
                source, plugin_cls, config, limit, force_mode, cron, storage
            )
            plugin_instance = fetch_result.get("plugin")

            if "skipped" in fetch_result:
                source_stats[source.id] = {
                    "fetched": 0,
                    "filtered": 0,
                    "skipped": fetch_result["skipped"],
                }
                total_sources_skipped += 1
                continue

            if "error" in fetch_result:
                source_stats[source.id] = {
                    "fetched": 0,
                    "filtered": 0,
                    "error": fetch_result["error"],
                }
                errors.append(fetch_result["error"])
                continue

            items = fetch_result["items"]

            if "plugin_metadata" in fetch_result:
                source.metadata = fetch_result["plugin_metadata"]

            items, seen_filtered_count = _filter_by_seen(items, source, storage, force_mode)
            items, lastid_filtered_count = _filter_by_last_item_id(items, source, force_mode)

            raw_fetched_count = fetch_result.get("raw_fetched_count", len(items))

            triggered_for_source, mismatches_for_source, matched_ids = _evaluate_and_match(
                items, source, rules, storage, force_mode, cron, debug
            )
            triggered.extend(triggered_for_source)
            mismatches.extend(mismatches_for_source)

            _update_source_tracking(source, storage, items, force_mode, plugin_instance)
            _mark_seen_items(storage, source, items, force_mode)

            fetched_count = len(items)
            triggered_filtered_count = 0

            matched_ids_set = matched_ids
            filtered_count = fetched_count - len(matched_ids_set)

            _display_source_summary(
                source,
                raw_fetched_count,
                fetched_count,
                seen_filtered_count,
                lastid_filtered_count,
                triggered_filtered_count,
                len(matched_ids),
                source.is_new,
                cron,
                silent,
            )

            source_stats[source.id] = {
                "fetched": fetched_count,
                "matched": len(matched_ids),
                "filtered": filtered_count,
                "seen_filtered": seen_filtered_count,
                "lastid_filtered": lastid_filtered_count,
                "triggered_filtered": triggered_filtered_count,
            }

            if force and items:
                if not cron:
                    click.echo(
                        "  → Force mode: NOT updating last_fetched_at or last_check",
                        err=True,
                    )

        _log_mismatches(storage, mismatches)

        global_on_error_action_ids = _get_global_on_error_action_ids()
        global_on_execution_action_ids = _get_global_on_execution_action_ids()

        for entry in triggered:
            rule = entry["rule"]
            item = entry["item"]
            source = entry["source"]

            triggered_at = datetime.now(timezone.utc)
            if not dry_run:
                total_actions = (0, 0, 0)
                action_results, actions_executed, actions_skipped, actions_failed = (
                    _execute_actions_for_trigger(
                        storage,
                        rule,
                        item,
                        source,
                        triggered_at,
                        resolved_workdir,
                        force,
                        ignore_enabled,
                        dry_run,
                        silent,
                        cron,
                        errors,
                        total_actions,
                    )
                )
                total_actions_executed += actions_executed
                total_actions_skipped += actions_skipped
                total_actions_failed += actions_failed

                _handle_global_hooks(
                    action_results,
                    rule,
                    errors,
                    storage,
                    resolved_workdir,
                    global_on_error_action_ids,
                    global_on_execution_action_ids,
                    item,
                    source,
                    item.title,
                    silent,
                    cron,
                    ignore_enabled,
                )

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
