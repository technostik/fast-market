from __future__ import annotations

import json
import uuid
from datetime import datetime

import click
import yaml

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted
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
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_add(plugin, identifier, description, fmt):
        """Add a new source to monitor."""
        storage = get_storage()

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
            created_at=datetime.now(),
        )

        storage.add_source(source)
        out_formatted(
            {
                "id": source.id,
                "plugin": source.plugin,
                "identifier": source.identifier,
                "description": source.description,
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
        out_formatted([s.__dict__ for s in sources], fmt)

    @setup_group.command("source-delete")
    @click.option("--id", "source_id", required=True, help="Source ID to delete")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_delete(source_id, fmt):
        """Delete a source."""
        storage = get_storage()
        storage.delete_source(source_id)
        out_formatted({"message": f"Source {source_id} deleted"}, fmt)

    @setup_group.command("action-add")
    @click.option("--name", required=True, help="Action name")
    @click.option(
        "--command",
        required=True,
        help="Shell command (use $VARIABLE for placeholders)",
    )
    @click.option("--description", help="Optional description")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_add(name, command, description, fmt):
        """Add a new action (shell script)."""
        storage = get_storage()

        action = Action(
            id=str(uuid.uuid4()),
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

    @setup_group.command("rule-add")
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
    def rule_add(name, rule_file, conditions, action_ids, description, fmt):
        """Add a new rule (conditions from file or inline)."""
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

        rule = Rule(
            id=str(uuid.uuid4()),
            name=name,
            conditions=conditions_data,
            action_ids=[aid.strip() for aid in action_ids.split(",")],
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

    @setup_group.command("list")
    @click.option(
        "--type",
        "type_",
        type=click.Choice(["sources", "actions", "rules"]),
        default="sources",
    )
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def list_items(type_, fmt):
        """List configured items."""
        storage = get_storage()
        if type_ == "sources":
            items = storage.get_all_sources()
            out_formatted([s.__dict__ for s in items], fmt)
        elif type_ == "actions":
            items = storage.get_all_actions()
            out_formatted([a.__dict__ for a in items], fmt)
        else:
            items = storage.get_all_rules()
            out_formatted([r.__dict__ for r in items], fmt)

    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
