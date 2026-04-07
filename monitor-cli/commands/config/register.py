from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import FoldedScalarString

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
from common.cli.helpers import get_editor
from common.core.paths import get_tool_config
from common.core.yaml_utils import dump_yaml
from core.models import Action, Rule, Source
from core.rule_formatter import RuleFormatter
from core.rule_parser import RuleParseError, RuleParser


def _get_config_path() -> Path:
    from common.core.paths import get_tool_config_path

    p = get_tool_config_path("monitor")
    return p.parent / "monitor.yaml"


def _load_yaml_config() -> dict | None:
    cfg_path = _get_config_path()
    if not cfg_path.exists():
        return None
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    with open(cfg_path) as f:
        return yaml.load(f)


def _save_yaml_config(data: dict) -> None:
    cfg_path = _get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    with open(cfg_path, "w") as f:
        yaml.dump(data, f)


def _merge_data(template: dict, data: dict) -> None:
    if data.get("sources"):
        template["sources"] = data["sources"]
    if data.get("actions"):
        template["actions"] = data["actions"]
    if data.get("rules"):
        template["rules"] = data["rules"]


def _sync_config_logic(
    storage, cfg_path: Path, plugin_manifests: dict, dry_run: bool = False
) -> dict:
    ruamel_yaml = YAML()
    with open(cfg_path) as f:
        config = ruamel_yaml.load(f)

    if not config:
        return {"error": "Config file is empty"}

    from core.config_schema import validate_config

    errors, warnings = validate_config(dict(config), plugin_manifests)
    if errors:
        return {"error": "Validation failed", "details": errors, "warnings": warnings}

    parser = RuleParser()
    changes = {
        "added": {"sources": [], "actions": [], "rules": []},
        "updated": {"sources": [], "actions": [], "rules": []},
        "removed": {"sources": [], "actions": [], "rules": []},
    }

    existing_sources = {s.id: s for s in storage.get_all_sources(include_disabled=True)}
    existing_actions = {a.id: a for a in storage.get_all_actions(include_disabled=True)}
    existing_rules = {r.id: r for r in storage.get_all_rules(include_disabled=True)}

    existing_sources_by_key = {}
    for s in storage.get_all_sources(include_disabled=True):
        key = (s.plugin, s.origin)
        existing_sources_by_key[key] = s

    sources_to_add = []
    sources_to_update = []
    actions_to_add = []
    actions_to_update = []
    rules_to_add = []
    rules_to_update = []

    for src in config.get("sources", []):
        src_id = src["id"]
        plugin = src["plugin"]
        origin = src["origin"]
        key = (plugin, origin)

        if src_id in existing_sources:
            existing_source = existing_sources[src_id]
            check_interval_val = src.get("check_interval")
            if isinstance(check_interval_val, str):
                from core.time_scheduler import parse_interval

                try:
                    check_interval_val = int(parse_interval(check_interval_val).total_seconds())
                except (ValueError, TypeError):
                    check_interval_val = None
            new_source = Source(
                id=src_id,
                plugin=plugin,
                origin=origin,
                description=src.get("description"),
                metadata=src.get("metadata", {}),
                enabled=src.get("enabled", True),
                created_at=existing_source.created_at,
                last_check=existing_source.last_check,
                last_fetched_at=existing_source.last_fetched_at,
                last_item_id=existing_source.last_item_id,
                check_interval=check_interval_val,
            )
            changes["updated"]["sources"].append(src_id)
            sources_to_update.append(new_source)
        elif key in existing_sources_by_key:
            existing_source = existing_sources_by_key[key]
            check_interval_val = src.get("check_interval")
            if isinstance(check_interval_val, str):
                from core.time_scheduler import parse_interval

                try:
                    check_interval_val = int(parse_interval(check_interval_val).total_seconds())
                except (ValueError, TypeError):
                    check_interval_val = None
            new_source = Source(
                id=src_id,
                plugin=plugin,
                origin=origin,
                description=src.get("description"),
                metadata=src.get("metadata", {}),
                enabled=src.get("enabled", True),
                created_at=existing_source.created_at,
                last_check=existing_source.last_check,
                last_fetched_at=existing_source.last_fetched_at,
                last_item_id=existing_source.last_item_id,
                check_interval=check_interval_val,
            )
            changes["updated"]["sources"].append(src_id)
            sources_to_update.append(new_source)
        else:
            check_interval_val = src.get("check_interval")
            if isinstance(check_interval_val, str):
                from core.time_scheduler import parse_interval

                try:
                    check_interval_val = int(parse_interval(check_interval_val).total_seconds())
                except (ValueError, TypeError):
                    check_interval_val = None
            new_source = Source(
                id=src_id,
                plugin=plugin,
                origin=origin,
                description=src.get("description"),
                metadata=src.get("metadata", {}),
                enabled=src.get("enabled", True),
                created_at=datetime.now(),
                check_interval=check_interval_val,
            )
            changes["added"]["sources"].append(src_id)
            sources_to_add.append(new_source)

    for act in config.get("actions", []):
        act_id = act["id"]

        if act_id in existing_actions:
            existing_action = existing_actions[act_id]
            new_action = Action(
                id=act_id,
                command=act["command"],
                description=act.get("description"),
                enabled=act.get("enabled", True),
                created_at=existing_action.created_at,
                last_run=existing_action.last_run,
                last_output=existing_action.last_output,
                last_exit_code=existing_action.last_exit_code,
            )
            changes["updated"]["actions"].append(act_id)
            actions_to_update.append(new_action)
        else:
            new_action = Action(
                id=act_id,
                command=act["command"],
                description=act.get("description"),
                enabled=act.get("enabled", True),
                created_at=datetime.now(),
            )
            changes["added"]["actions"].append(act_id)
            actions_to_add.append(new_action)

    for rule in config.get("rules", []):
        rule_id = rule.get("id", f"rule_#{config.get('rules', []).index(rule)}")
        
        # Validate required fields
        if "conditions" not in rule:
            return {"error": f"Rule '{rule_id}' is missing required field: 'conditions'"}
        if "action_ids" not in rule or not rule.get("action_ids"):
            return {"error": f"Rule '{rule_id}' is missing required field: 'action_ids'"}
        
        # Handle conditions: convert boolean to proper format
        conditions_value = rule["conditions"]
        if isinstance(conditions_value, bool):
            # true = always match (empty all), false = never match (empty any)
            conditions = {"all": []} if conditions_value else {"any": []}
        elif isinstance(conditions_value, str):
            try:
                conditions = parser.parse(conditions_value)
            except RuleParseError as e:
                return {"error": f"Failed to parse rule '{rule_id}': {e}"}
        else:
            return {
                "error": f"Rule '{rule_id}' has invalid 'conditions' type. "
                f"Expected string DSL expression or boolean (true/false), got {type(conditions_value).__name__}."
            }

        schedule = None
        if rule.get("schedule"):
            sched = rule["schedule"]
            if isinstance(sched, str):
                # String schedule is treated as cron expression
                schedule = {"cron": sched}
            elif isinstance(sched, dict):
                if "cron" in sched:
                    schedule = {"cron": sched["cron"]}
                elif "interval" in sched:
                    schedule = {"interval": sched["interval"]}

        action_ids = rule.get("action_ids", [])
        defined_action_ids = {a["id"] for a in config.get("actions", [])}
        for aid in action_ids:
            if aid not in defined_action_ids and aid not in existing_actions:
                return {"error": f"Rule '{rule_id}' references unknown action '{aid}'"}

        if rule_id in existing_rules:
            existing_rule = existing_rules[rule_id]
            new_rule = Rule(
                id=rule_id,
                conditions=conditions,
                action_ids=action_ids,
                description=rule.get("description"),
                enabled=rule.get("enabled", True),
                created_at=existing_rule.created_at,
                schedule=schedule,
                timezone=rule.get("timezone", "UTC"),
                last_triggered_at=existing_rule.last_triggered_at,
            )
            changes["updated"]["rules"].append(rule_id)
            rules_to_update.append(new_rule)
        else:
            new_rule = Rule(
                id=rule_id,
                conditions=conditions,
                action_ids=action_ids,
                description=rule.get("description"),
                enabled=rule.get("enabled", True),
                created_at=datetime.now(),
                schedule=schedule,
                timezone=rule.get("timezone", "UTC"),
            )
            changes["added"]["rules"].append(rule_id)
            rules_to_add.append(new_rule)

    for src_id in existing_sources:
        if src_id not in [s.id for s in sources_to_update] and src_id not in [
            s.id for s in sources_to_add
        ]:
            changes["removed"]["sources"].append(src_id)

    for act_id in existing_actions:
        if act_id not in [a.id for a in actions_to_update] and act_id not in [
            a.id for a in actions_to_add
        ]:
            changes["removed"]["actions"].append(act_id)

    for rule_id in existing_rules:
        if rule_id not in [r.id for r in rules_to_update] and rule_id not in [
            r.id for r in rules_to_add
        ]:
            changes["removed"]["rules"].append(rule_id)

    if dry_run:
        return {"dry_run": True, "changes": changes}

    for new_source in sources_to_add:
        storage.add_source(new_source)

    for new_source in sources_to_update:
        storage.update_source(new_source)

    for new_action in actions_to_add:
        storage.add_action(new_action)

    for new_action in actions_to_update:
        storage.update_action(new_action)

    for new_rule in rules_to_add:
        storage.add_rule(new_rule)

    for new_rule in rules_to_update:
        storage.update_rule(new_rule)

    for src_id in changes["removed"]["sources"]:
        storage.delete_source(src_id)

    for act_id in changes["removed"]["actions"]:
        storage.delete_action(act_id)

    for rule_id in changes["removed"]["rules"]:
        storage.delete_rule(rule_id)

    return {"message": "Configuration synced successfully", "changes": changes}


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("config")
    def config_group():
        """Manage configuration from YAML file (source of truth)."""
        pass

    @config_group.command("path")
    def show_path():
        """Show the configuration file path."""
        cfg_path = _get_config_path()
        click.echo(f"Config path: {cfg_path}")
        if cfg_path.exists():
            click.echo(
                f"Config exists: yes (modified: {datetime.fromtimestamp(cfg_path.stat().st_mtime).isoformat()})"
            )
        else:
            click.echo("Config exists: no (run 'monitor config export' to create)")

    @config_group.command("export")
    @click.option("--format", "fmt", type=click.Choice(["yaml", "text"]), default="yaml")
    def export_config(fmt):
        """Export current database configuration to YAML file."""
        storage = get_storage()
        cfg_path = _get_config_path()

        sources = storage.get_all_sources(include_disabled=True)
        actions = storage.get_all_actions(include_disabled=True)
        rules = storage.get_all_rules(include_disabled=True)

        formatter = RuleFormatter()

        yaml_data = {
            "sources": [],
            "actions": [],
            "rules": [],
        }

        for s in sources:
            yaml_data["sources"].append(
                {
                    "id": s.id,
                    "plugin": s.plugin,
                    "origin": s.origin,
                    "description": s.description,
                    "enabled": s.enabled,
                    "metadata": s.metadata or {},
                }
            )

        for a in actions:
            yaml_data["actions"].append(
                {
                    "id": a.id,
                    "command": a.command,
                    "description": a.description,
                    "enabled": a.enabled,
                }
            )

        for r in rules:
            conditions_str = formatter.format(r.conditions, pretty=True)
            if "\n" in conditions_str:
                conditions_str = FoldedScalarString(conditions_str)
            rule_dict = {
                "id": r.id,
                "description": r.description,
                "enabled": r.enabled,
                "conditions": conditions_str,
                "action_ids": r.action_ids,
            }
            if r.schedule:
                rule_dict["schedule"] = r.schedule
            if r.timezone and r.timezone != "UTC":
                rule_dict["timezone"] = r.timezone
            yaml_data["rules"].append(rule_dict)

        if fmt == "yaml":
            ruamel_yaml = YAML()
            ruamel_yaml.preserve_quotes = True
            ruamel_yaml.default_flow_style = False
            ruamel_yaml.width = 120

            template = yaml.safe_load(get_template())
            _merge_data(template, yaml_data)

            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg_path, "w") as f:
                ruamel_yaml.dump(template, f)

            click.echo(f"Configuration exported to: {cfg_path}")
        else:
            click.echo(dump_yaml(yaml_data, sort_keys=False))

    @config_group.command("sync")
    @click.option("--dry-run", is_flag=True, help="Show changes without applying")
    @click.option("--force", is_flag=True, help="Skip YAML validation, apply even with errors")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def sync_config(dry_run, force, fmt):
        """Import YAML configuration to database (YAML is source of truth)."""
        storage = get_storage()
        cfg_path = _get_config_path()

        if not cfg_path.exists():
            out_formatted(
                {
                    "error": f"Config file not found at {cfg_path}. Run 'monitor config export' first.",
                    "hint": "This will export your current database configuration to YAML",
                },
                fmt,
            )
            return

        try:
            ruamel_yaml = YAML()
            with open(cfg_path) as f:
                config = ruamel_yaml.load(f)
        except Exception as e:
            if force:
                with open(cfg_path) as f:
                    raw_content = f.read()
                out_formatted(
                    {"error": f"Failed to parse YAML: {e}", "raw_content": raw_content}, fmt
                )
            else:
                out_formatted(
                    {
                        "error": f"Failed to parse YAML: {e}",
                        "hint": "Use --force to see raw content",
                    },
                    fmt,
                )
            return

        if not config:
            out_formatted({"error": "Config file is empty"}, fmt)
            return

        from core.config_schema import validate_config

        errors, warnings = validate_config(dict(config), plugin_manifests)
        if errors:
            if force:
                warnings.extend([f"VALIDATION_ERROR: {e}" for e in errors])
            else:
                out_formatted(
                    {"error": "Validation failed", "details": errors, "warnings": warnings}, fmt
                )
                return

        result = _sync_config_logic(storage, cfg_path, plugin_manifests, dry_run)
        if "error" in result:
            out_formatted(result, fmt)
            return

        if warnings:
            result["warnings"] = warnings
        out_formatted(result, fmt)

    @config_group.command("validate")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.option("--force", is_flag=True, help="Show raw content even if YAML is invalid")
    def validate_config_cmd(fmt, force):
        """Validate the YAML configuration file."""
        cfg_path = _get_config_path()

        if not cfg_path.exists():
            out_formatted({"error": f"Config file not found at {cfg_path}"}, fmt)
            return

        try:
            ruamel_yaml = YAML()
            with open(cfg_path) as f:
                config = ruamel_yaml.load(f)
        except Exception as e:
            if force:
                with open(cfg_path) as f:
                    raw_content = f.read()
                out_formatted(
                    {"error": f"Failed to parse YAML: {e}", "raw_content": raw_content}, fmt
                )
            else:
                out_formatted(
                    {
                        "error": f"Failed to parse YAML: {e}",
                        "hint": "Use --force to see raw content",
                    },
                    fmt,
                )
            return

        if not config:
            out_formatted({"error": "Config file is empty"}, fmt)
            return

        from core.config_schema import validate_config

        errors, warnings = validate_config(dict(config), plugin_manifests)

        if errors:
            out_formatted({"valid": False, "errors": errors, "warnings": warnings}, fmt)
        else:
            result = {"valid": True, "message": "Configuration is valid"}
            if warnings:
                result["warnings"] = warnings
            out_formatted(result, fmt)

    @config_group.command("edit")
    @click.option("--editor", help="Editor to use (default: $EDITOR or nano)")
    @click.option("--no-sync", is_flag=True, help="Skip automatic sync after editing")
    def edit_config(editor, no_sync):
        """Open the configuration file in an editor and sync automatically."""
        cfg_path = _get_config_path()

        if not cfg_path.exists():
            click.echo(f"Config file not found at {cfg_path}.")
            click.echo("Run 'monitor config export' first to create it.")
            return

        editor_cmd = editor or get_editor()
        editor_path = shutil.which(editor_cmd)

        if not editor_path:
            click.echo(
                f"Error: Editor '{editor_cmd}' not found. Install it or set $EDITOR.", err=True
            )
            return

        result = subprocess.run([editor_cmd, str(cfg_path)], check=False)

        if result.returncode != 0:
            click.echo("Editor closed with error.", err=True)
            return

        click.echo(f"Config file saved: {cfg_path}")

        if no_sync:
            click.echo("Skipping sync (use 'monitor config sync' to sync manually)")
            return

        storage = get_storage()
        sync_result = _sync_config_logic(storage, cfg_path, plugin_manifests, dry_run=False)

        if "error" in sync_result:
            click.echo(f"Sync error: {sync_result['error']}", err=True)
            if "details" in sync_result:
                for err_detail in sync_result["details"]:
                    click.echo(f"  - {err_detail}", err=True)
            return

        changes = sync_result.get("changes", {})
        added = changes.get("added", {})
        updated = changes.get("updated", {})
        removed = changes.get("removed", {})

        total = (
            len(added.get("sources", []))
            + len(added.get("actions", []))
            + len(added.get("rules", []))
            + len(updated.get("sources", []))
            + len(updated.get("actions", []))
            + len(updated.get("rules", []))
            + len(removed.get("sources", []))
            + len(removed.get("actions", []))
            + len(removed.get("rules", []))
        )

        if total > 0:
            click.echo(f"Synced: {total} change(s)")
            if added["sources"] or added["actions"] or added["rules"]:
                click.echo(
                    f"  + Added: {len(added.get('sources', []))} sources, {len(added.get('actions', []))} actions, {len(added.get('rules', []))} rules"
                )
            if updated["sources"] or updated["actions"] or updated["rules"]:
                click.echo(
                    f"  ~ Updated: {len(updated.get('sources', []))} sources, {len(updated.get('actions', []))} actions, {len(updated.get('rules', []))} rules"
                )
            if removed["sources"] or removed["actions"] or removed["rules"]:
                click.echo(
                    f"  - Removed: {len(removed.get('sources', []))} sources, {len(removed.get('actions', []))} actions, {len(removed.get('rules', []))} rules"
                )
        else:
            click.echo("No changes detected")

    @config_group.command("template")
    def show_template():
        """Show the configuration template."""
        click.echo(get_template())

    return CommandManifest(
        name="config",
        click_command=config_group,
    )


def get_template() -> str:
    from core.config_schema import get_config_template

    return get_config_template()
