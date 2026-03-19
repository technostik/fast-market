from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted, to_dict
from core.models import Source, Action, Rule


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group():
        """Configure sources, actions, and rules."""
        pass

    @setup_group.command("source-add")
    @click.option("--plugin", type=click.Choice(["youtube", "rss"]), required=True)
    @click.option("--identifier", required=True, help="Channel ID, @handle, or RSS URL")
    @click.option("--description", help="Optional description")
    @click.option(
        "--meta", multiple=True, help="Metadata key=value pairs (can be used multiple times)"
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_add(plugin, identifier, description, meta, fmt):
        """Add a new source to monitor with optional metadata."""
        storage = get_storage()

        metadata = {}
        for m in meta:
            if "=" not in m:
                raise click.BadParameter(f"Metadata must be key=value format, got: {m}")
            key, value = m.split("=", 1)
            metadata[key.strip()] = value.strip()

        plugin_class = plugin_manifests[plugin].source_plugin_class
        temp_config = plugin_class({"identifier": identifier}, {"identifier": identifier})
        if not temp_config.validate_identifier(identifier):
            out_formatted({"error": f"Invalid identifier for {plugin} plugin"}, fmt)
            return

        source = Source(
            id=str(uuid.uuid4()),
            plugin=plugin,
            identifier=identifier,
            description=description,
            metadata=metadata,
            created_at=datetime.now(),
        )

        storage.add_source(source)
        out_formatted(
            {
                "id": source.id,
                "plugin": source.plugin,
                "identifier": source.identifier,
                "description": source.description,
                "metadata": metadata,
                "message": "Source added successfully",
            },
            fmt,
        )

    @setup_group.command("source-list")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_list(fmt):
        """List all configured sources."""
        storage = get_storage()
        sources = storage.get_all_sources()
        out_formatted([to_dict(s) for s in sources], fmt)

    @setup_group.command("source-delete")
    @click.option("--id", "source_id", required=True, help="Source ID to delete")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_delete(source_id, fmt):
        """Delete a source."""
        storage = get_storage()
        storage.delete_source(source_id)
        out_formatted({"message": f"Source {source_id} deleted"}, fmt)

    @setup_group.command("source-edit")
    @click.argument("source_id")
    @click.option("--description", help="New description")
    @click.option("--meta", multiple=True, help="Metadata key=value pairs (adds/updates)")
    @click.option("--enable/--disable", default=None, help="Enable or disable source")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_edit(source_id, description, meta, enable, fmt):
        """Edit an existing source."""
        storage = get_storage()
        existing = storage.get_source(source_id)
        if not existing:
            out_formatted({"error": f"Source {source_id} not found"}, fmt)
            return

        if description is not None:
            existing.description = description

        for m in meta:
            if "=" not in m:
                raise click.BadParameter(f"Metadata must be key=value format, got: {m}")
            key, value = m.split("=", 1)
            existing.metadata[key.strip()] = value.strip()

        if enable is not None:
            existing.enabled = enable

        storage.update_source(existing)
        out_formatted(
            {"id": existing.id, "message": "Source updated", "source": to_dict(existing)}, fmt
        )

    @setup_group.command("action-add")
    @click.option("--id", "custom_id", help="Custom ID (instead of auto-generated)")
    @click.option("--replace-id", help="Replace existing action with this ID")
    @click.option("--name", required=True, help="Action name")
    @click.option(
        "--command",
        required=True,
        help="Shell command (use $VARIABLE for placeholders)",
    )
    @click.option("--description", help="Optional description")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_add(custom_id, replace_id, name, command, description, fmt):
        """Add or replace an action."""
        storage = get_storage()

        if replace_id:
            existing = storage.get_action(replace_id)
            if not existing:
                out_formatted({"error": f"Action {replace_id} not found"}, fmt)
                return

            existing.name = name
            existing.command = command
            existing.description = description
            storage.update_action(existing)
            out_formatted({"id": replace_id, "message": "Action replaced"}, fmt)
            return

        action_id = custom_id or str(uuid.uuid4())

        if custom_id and storage.get_action(custom_id):
            out_formatted(
                {"error": f"Action ID {custom_id} already exists. Use --replace-id to update."},
                fmt,
            )
            return

        action = Action(
            id=action_id,
            name=name,
            command=command,
            description=description,
            created_at=datetime.now(),
        )

        storage.add_action(action)
        out_formatted(
            {
                "id": action.id,
                "name": action.name,
                "description": action.description,
                "message": "Action added successfully",
            },
            fmt,
        )

    @setup_group.command("action-list")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_list(fmt):
        """List all configured actions."""
        storage = get_storage()
        actions = storage.get_all_actions()
        out_formatted(
            [
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "command": a.command,
                    "last_run": a.last_run.isoformat() if a.last_run else None,
                    "last_exit_code": a.last_exit_code,
                }
                for a in actions
            ],
            fmt,
        )

    @setup_group.command("action-delete")
    @click.option("--id", "action_id", required=True, help="Action ID to delete")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_delete(action_id, fmt):
        """Delete an action."""
        storage = get_storage()
        storage.delete_action(action_id)
        out_formatted({"message": f"Action {action_id} deleted"}, fmt)

    @setup_group.command("action-edit")
    @click.argument("action_id")
    @click.option("--name", help="New action name")
    @click.option("--command", help="New shell command")
    @click.option("--description", help="New description")
    @click.option("--enable/--disable", default=None, help="Enable or disable action")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_edit(action_id, name, command, description, enable, fmt):
        """Edit an existing action."""
        storage = get_storage()
        existing = storage.get_action(action_id)
        if not existing:
            out_formatted({"error": f"Action {action_id} not found"}, fmt)
            return

        if name is not None:
            existing.name = name
        if command is not None:
            existing.command = command
        if description is not None:
            existing.description = description
        if enable is not None:
            existing.enabled = enable

        storage.update_action(existing)
        out_formatted(
            {"id": existing.id, "message": "Action updated", "action": to_dict(existing)}, fmt
        )

    @setup_group.command("rule-add")
    @click.option("--id", "custom_id", help="Custom ID (instead of auto-generated)")
    @click.option("--replace-id", help="Replace existing rule with this ID")
    @click.option("--name", required=True, help="Rule name")
    @click.option(
        "--rule-file",
        type=click.Path(exists=True),
        help="YAML/JSON file with rule conditions",
    )
    @click.option(
        "--conditions",
        help="JSON string with rule conditions (alternative to --rule-file)",
    )
    @click.option("--action-ids", required=True, help="Comma-separated action IDs")
    @click.option("--description", help="Optional description")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_add(custom_id, replace_id, name, rule_file, conditions, action_ids, description, fmt):
        """Add or replace a rule."""
        storage = get_storage()

        if rule_file:
            with open(rule_file) as f:
                if rule_file.endswith(".json"):
                    conditions_data = json.load(f)
                else:
                    conditions_data = yaml.safe_load(f)
        elif conditions:
            conditions_data = json.loads(conditions)
        else:
            out_formatted({"error": "Either --rule-file or --conditions required"}, fmt)
            return

        action_id_list = [aid.strip() for aid in action_ids.split(",")]

        if replace_id:
            existing = storage.get_rule(replace_id)
            if not existing:
                out_formatted({"error": f"Rule {replace_id} not found"}, fmt)
                return

            existing.name = name
            existing.conditions = conditions_data
            existing.action_ids = action_id_list
            existing.description = description
            storage.update_rule(existing)
            out_formatted({"id": replace_id, "message": "Rule replaced"}, fmt)
            return

        rule_id = custom_id or str(uuid.uuid4())

        if custom_id and storage.get_rule(custom_id):
            out_formatted(
                {"error": f"Rule ID {custom_id} already exists. Use --replace-id to update."},
                fmt,
            )
            return

        rule = Rule(
            id=rule_id,
            name=name,
            conditions=conditions_data,
            action_ids=action_id_list,
            description=description,
            created_at=datetime.now(),
        )

        storage.add_rule(rule)
        out_formatted(
            {
                "id": rule.id,
                "name": rule.name,
                "conditions": rule.conditions,
                "action_ids": rule.action_ids,
                "message": "Rule added successfully",
            },
            fmt,
        )

    @setup_group.command("rule-list")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_list(fmt):
        """List all configured rules."""
        storage = get_storage()
        rules = storage.get_all_rules()
        out_formatted(
            [
                {
                    "id": r.id,
                    "name": r.name,
                    "conditions": r.conditions,
                    "action_ids": r.action_ids,
                    "description": r.description,
                }
                for r in rules
            ],
            fmt,
        )

    @setup_group.command("rule-delete")
    @click.option("--id", "rule_id", required=True, help="Rule ID to delete")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_delete(rule_id, fmt):
        """Delete a rule."""
        storage = get_storage()
        storage.delete_rule(rule_id)
        out_formatted({"message": f"Rule {rule_id} deleted"}, fmt)

    @setup_group.command("rule-edit")
    @click.argument("rule_id")
    @click.option("--name", help="New rule name")
    @click.option(
        "--rule-file",
        type=click.Path(exists=True),
        help="YAML/JSON file with new rule conditions",
    )
    @click.option(
        "--conditions",
        help="JSON string with new rule conditions",
    )
    @click.option("--action-ids", help="Comma-separated action IDs")
    @click.option("--description", help="New description")
    @click.option("--enable/--disable", default=None, help="Enable or disable rule")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_edit(rule_id, name, rule_file, conditions, action_ids, description, enable, fmt):
        """Edit an existing rule."""
        storage = get_storage()
        existing = storage.get_rule(rule_id)
        if not existing:
            out_formatted({"error": f"Rule {rule_id} not found"}, fmt)
            return

        if name is not None:
            existing.name = name

        if rule_file:
            with open(rule_file) as f:
                if rule_file.endswith(".json"):
                    existing.conditions = json.load(f)
                else:
                    existing.conditions = yaml.safe_load(f)
        elif conditions:
            existing.conditions = json.loads(conditions)

        if action_ids is not None:
            existing.action_ids = [aid.strip() for aid in action_ids.split(",")]

        if description is not None:
            existing.description = description

        if enable is not None:
            existing.enabled = enable

        storage.update_rule(existing)
        out_formatted(
            {"id": existing.id, "message": "Rule updated", "rule": to_dict(existing)}, fmt
        )

    @setup_group.command("rename")
    @click.option("--from-id", required=True, help="Current ID to rename")
    @click.option("--to-id", required=True, help="New ID")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rename_id(from_id, to_id, fmt):
        """Rename an entity ID (source, action, or rule) and update all references."""
        storage = get_storage()
        entity_type, message = storage.rename_id(from_id, to_id)
        if entity_type:
            out_formatted({"type": entity_type, "message": message}, fmt)
        else:
            out_formatted({"error": message}, fmt)

    @setup_group.command("config-show")
    @click.option("--export", type=click.Choice(["yaml", "json"]), help="Export all configuration")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def show_config(export, fmt):
        """Show configuration files and optionally export all configs."""
        storage = get_storage()

        db_path = Path(storage.db_path)
        config_paths = {
            "database": str(db_path),
            "config_dir": str(db_path.parent),
            "log_dir": str(Path.home() / ".local" / "state" / "fast-market" / "monitor" / "logs"),
        }

        if export:
            all_configs = {
                "sources": [to_dict(s) for s in storage.get_all_sources()],
                "actions": [to_dict(a) for a in storage.get_all_actions()],
                "rules": [to_dict(r) for r in storage.get_all_rules()],
                "metadata": {
                    "version": "0.1.0",
                    "exported_at": datetime.now().isoformat(),
                },
            }

            if export == "yaml":
                click.echo(
                    yaml.dump(
                        all_configs, allow_unicode=True, default_flow_style=False, sort_keys=False
                    )
                )
            else:
                click.echo(json.dumps(all_configs, indent=2, default=str))
        else:
            out_formatted(config_paths, fmt)

    @setup_group.command("list")
    @click.option(
        "--type",
        "type_",
        type=click.Choice(["sources", "actions", "rules", "all"]),
        default="all",
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def list_items(type_, fmt):
        """List configured items."""
        storage = get_storage()
        if type_ == "all":
            sources = [to_dict(s) for s in storage.get_all_sources()]
            actions = [to_dict(a) for a in storage.get_all_actions()]
            rules = [to_dict(r) for r in storage.get_all_rules()]
            out_formatted({"sources": sources, "actions": actions, "rules": rules}, fmt)
        elif type_ == "sources":
            out_formatted([to_dict(s) for s in storage.get_all_sources()], fmt)
        elif type_ == "actions":
            out_formatted([to_dict(a) for a in storage.get_all_actions()], fmt)
        else:
            out_formatted([to_dict(r) for r in storage.get_all_rules()], fmt)

    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
