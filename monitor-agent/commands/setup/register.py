from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.helpers import get_storage, out_formatted, to_dict
from core.models import Source, Action, Rule
from core.rule_parser import RuleParser, RuleParseError
from core.rule_formatter import RuleFormatter
from core.time_scheduler import validate_cron_expression, validate_interval_expression


def _interactive_source_edit(source, storage, editor_cmd, fmt):
    """Open an interactive editor to edit a source."""
    meta_yaml = ""
    if source.metadata:
        meta_lines = [f"  {k}: {v}" for k, v in source.metadata.items()]
        meta_yaml = "metadata:\n" + "\n".join(meta_lines) + "\n"

    template = f"""# Edit source: {source.id}
# Lines starting with # are comments and will be ignored.
#
# Available options:
#   name: Human-readable name (optional)
#   description: Description of this source
#   enabled: true or false
#   metadata: Key-value pairs for custom fields

plugin: {source.plugin}
identifier: {source.identifier}
name: {source.name or ""}
description: {source.description or ""}
enabled: {str(source.enabled).lower()}
{meta_yaml}""".strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(template)

    try:
        while True:
            editor_path = shutil.which(editor_cmd)
            if not editor_path:
                click.echo(
                    f"Error: Editor '{editor_cmd}' not found. Install it or set $EDITOR.", err=True
                )
                return

            result = subprocess.run(
                [editor_cmd, str(tmp_path)],
                check=False,
            )

            if result.returncode != 0:
                click.echo("Editor closed with error. Source not saved.", err=True)
                return

            with open(tmp_path) as f:
                content = f.read()

            try:
                edited_source = yaml.safe_load(content)
            except yaml.YAMLError as e:
                click.echo(f"YAML parse error: {e}", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            if not edited_source or not isinstance(edited_source, dict):
                click.echo("Error: Invalid YAML format", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            enabled_str = edited_source.get("enabled", "")
            if isinstance(enabled_str, str):
                source.enabled = enabled_str.lower() in ("true", "1", "yes")
            elif isinstance(enabled_str, bool):
                source.enabled = enabled_str

            source.name = edited_source.get("name") or None
            source.description = edited_source.get("description") or None

            if edited_source.get("metadata"):
                if isinstance(edited_source["metadata"], dict):
                    source.metadata = edited_source["metadata"]
                else:
                    click.echo("Error: metadata must be a dictionary", err=True)
                    click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                    input()
                    continue

            storage.update_source(source)
            out_formatted(
                {"id": source.id, "message": "Source updated", "source": to_dict(source)}, fmt
            )
            return

    finally:
        tmp_path.unlink(missing_ok=True)


def _interactive_action_edit(action, storage, editor_cmd, fmt):
    """Open an interactive editor to edit an action."""
    template = f"""# Edit action: {action.id}
# Lines starting with # are comments and will be ignored.
#
# Available options:
#   name: Human-readable action name
#   description: Description of what this action does
#   command: Shell command to execute (use $VARIABLE for placeholders)
#   enabled: true or false
#
# Placeholders available in commands:
#   $ITEM_TITLE, $ITEM_URL, $ITEM_ID, $ITEM_TIMESTAMP
#   $SOURCE_ID, $SOURCE_NAME, $SOURCE_PLUGIN
#   $RULE_NAME, $RULE_ID
#   $SOURCE_META_<KEY> (e.g., $SOURCE_META_THEME)

name: {action.name}
description: {action.description or ""}
command: |
  {action.command}
enabled: {str(action.enabled).lower()}
""".strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(template)

    try:
        while True:
            editor_path = shutil.which(editor_cmd)
            if not editor_path:
                click.echo(
                    f"Error: Editor '{editor_cmd}' not found. Install it or set $EDITOR.", err=True
                )
                return

            result = subprocess.run(
                [editor_cmd, str(tmp_path)],
                check=False,
            )

            if result.returncode != 0:
                click.echo("Editor closed with error. Action not saved.", err=True)
                return

            with open(tmp_path) as f:
                content = f.read()

            try:
                edited_action = yaml.safe_load(content)
            except yaml.YAMLError as e:
                click.echo(f"YAML parse error: {e}", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            if not edited_action or not isinstance(edited_action, dict):
                click.echo("Error: Invalid YAML format", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            if not edited_action.get("command"):
                click.echo("Error: command field cannot be empty", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            enabled_str = edited_action.get("enabled", "")
            if isinstance(enabled_str, str):
                action.enabled = enabled_str.lower() in ("true", "1", "yes")
            elif isinstance(enabled_str, bool):
                action.enabled = enabled_str

            action.name = edited_action.get("name", action.name)
            action.description = edited_action.get("description") or None
            action.command = edited_action.get("command", action.command)

            storage.update_action(action)
            out_formatted(
                {"id": action.id, "message": "Action updated", "action": to_dict(action)}, fmt
            )
            return

    finally:
        tmp_path.unlink(missing_ok=True)


def _interactive_rule_edit(rule, parser, formatter, storage, editor_cmd, fmt):
    """Open an interactive editor to edit a rule in DSL format."""
    current_dsl = formatter.format(rule.conditions, pretty=True)

    schedule_yaml = ""
    if rule.schedule:
        if "cron" in rule.schedule:
            schedule_yaml = f"schedule:\n  cron: {rule.schedule['cron']}\n"
        elif "interval" in rule.schedule:
            schedule_yaml = f"schedule:\n  interval: {rule.schedule['interval']}\n"
    else:
        schedule_yaml = '# schedule:\n#   cron: "0 * * * *"  # uncomment to add cron schedule\n#   interval: "1h"  # uncomment to add interval schedule\n'

    actions_yaml = ", ".join(rule.action_ids)

    template = f"""# Edit rule: {rule.id}
# Lines starting with # are comments and will be ignored.
#
# DSL Condition Syntax:
#   - Operators: ==, !=, >, <, >=, <=, contains, matches
#   - Logical: and, or, parentheses for grouping
#   Examples:
#     content_type == 'video'
#     extra.duration > 600
#     title matches '.*AI.*'
#     (source == 'youtube' and type == 'video') or priority == 'high'
#
# Schedule (optional, uncomment one):
{schedule_yaml}#
# Available options:
#   schedule: cron expression like "0 * * * *" (minute hour day month weekday)
#   schedule: interval like "30m", "1h", "2h", "1d"
#   timezone: e.g., "UTC", "America/New_York"

name: {rule.name}
description: {rule.description or ""}
actions: [{actions_yaml}]
timezone: {rule.timezone}
conditions: |
  {current_dsl}
""".strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(template)

    try:
        while True:
            editor_path = shutil.which(editor_cmd)
            if not editor_path:
                click.echo(
                    f"Error: Editor '{editor_cmd}' not found. Install it or set $EDITOR.", err=True
                )
                return

            result = subprocess.run(
                [editor_cmd, str(tmp_path)],
                check=False,
            )

            if result.returncode != 0:
                click.echo("Editor closed with error. Rule not saved.", err=True)
                return

            with open(tmp_path) as f:
                content = f.read()

            try:
                edited_rule = yaml.safe_load(content)
            except yaml.YAMLError as e:
                click.echo(f"YAML parse error: {e}", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            new_conditions_str = edited_rule.get("conditions", "").strip()
            if new_conditions_str:
                try:
                    new_conditions = parser.parse(new_conditions_str)
                except RuleParseError as e:
                    click.echo(f"DSL parse error: {e}", err=True)
                    click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                    input()
                    continue
            else:
                click.echo("Error: conditions field cannot be empty", err=True)
                click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                input()
                continue

            if edited_rule.get("schedule"):
                sched = edited_rule["schedule"]
                if isinstance(sched, dict):
                    if "cron" in sched:
                        if not validate_cron_expression(sched["cron"]):
                            click.echo(f"Invalid cron expression: {sched['cron']}", err=True)
                            click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                            input()
                            continue
                    elif "interval" in sched:
                        if not validate_interval_expression(sched["interval"]):
                            click.echo(f"Invalid interval: {sched['interval']}", err=True)
                            click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                            input()
                            continue
                    else:
                        click.echo("Invalid schedule format. Use 'cron' or 'interval'.", err=True)
                        click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                        input()
                        continue
                else:
                    click.echo(
                        "Invalid schedule format. Use a dict with 'cron' or 'interval'.", err=True
                    )
                    click.echo("Press Enter to re-edit, Ctrl+C to cancel...", err=True)
                    input()
                    continue

            rule.name = edited_rule.get("name", rule.name)
            rule.description = edited_rule.get("description") or None
            rule.conditions = new_conditions
            rule.timezone = edited_rule.get("timezone", rule.timezone)

            actions_str = edited_rule.get("actions", "")
            if isinstance(actions_str, str):
                rule.action_ids = [
                    a.strip()
                    for a in actions_str.replace("[", "").replace("]", "").split(",")
                    if a.strip()
                ]
            elif isinstance(actions_str, list):
                rule.action_ids = [str(a).strip() for a in actions_str if a]

            if edited_rule.get("schedule"):
                sched = edited_rule["schedule"]
                rule.schedule = {"cron" if "cron" in sched else "interval": list(sched.values())[0]}
            else:
                rule.schedule = None

            storage.update_rule(rule)
            click.echo(f"Rule '{rule.name}' updated successfully.")
            return

    finally:
        tmp_path.unlink(missing_ok=True)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group():
        """Configure sources, actions, and rules."""
        pass

    plugin_choices = list(plugin_manifests.keys())

    @setup_group.command("source-add")
    @click.option("--plugin", type=click.Choice(plugin_choices), required=True)
    @click.option("--identifier", required=True, help="Channel ID, search keywords, or RSS URL")
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
    @click.option(
        "-i",
        "--interactive",
        "interactive",
        is_flag=True,
        help="Open interactive editor",
    )
    @click.option("--description", help="New description")
    @click.option("--meta", multiple=True, help="Metadata key=value pairs (adds/updates)")
    @click.option("--enable/--disable", default=None, help="Enable or disable source")
    @click.option("--editor", help="Editor to use (default: $EDITOR or nano)")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def source_edit(source_id, interactive, description, meta, enable, editor, fmt):
        """Edit an existing source interactively or with options.

        Use -i/--interactive to open the editor.

        Examples:
            monitor setup source-edit my-source -i  # Interactive editor
            monitor setup source-edit my-source --description "New desc"
            monitor setup source-edit my-source --meta theme=tech --enable
        """
        storage = get_storage()
        existing = storage.get_source(source_id)
        if not existing:
            out_formatted({"error": f"Source {source_id} not found"}, fmt)
            return

        if interactive:
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_source_edit(existing, storage, editor_cmd, fmt)
            return
        elif description is None and not meta and enable is None:
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_source_edit(existing, storage, editor_cmd, fmt)
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
    @click.option(
        "-i",
        "--interactive",
        "interactive",
        is_flag=True,
        help="Open interactive editor",
    )
    @click.option("--name", help="New action name")
    @click.option("--command", help="New shell command")
    @click.option("--description", help="New description")
    @click.option("--enable/--disable", default=None, help="Enable or disable action")
    @click.option("--editor", help="Editor to use (default: $EDITOR or nano)")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def action_edit(action_id, interactive, name, command, description, enable, editor, fmt):
        """Edit an existing action interactively or with options.

        Use -i/--interactive to open the editor.

        Examples:
            monitor setup action-edit my-action -i  # Interactive editor
            monitor setup action-edit my-action --name "New name"
            monitor setup action-edit my-action --command 'curl ...'
        """
        storage = get_storage()
        existing = storage.get_action(action_id)
        if not existing:
            out_formatted({"error": f"Action {action_id} not found"}, fmt)
            return

        if interactive:
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_action_edit(existing, storage, editor_cmd, fmt)
            return
        elif name is None and command is None and description is None and enable is None:
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_action_edit(existing, storage, editor_cmd, fmt)
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
        help="Condition DSL string (e.g., \"content_type == 'video' and duration > 600\")",
    )
    @click.option("--action-ids", required=True, help="Comma-separated action IDs")
    @click.option("--description", help="Optional description")
    @click.option("--cron", help="Cron schedule (e.g., '0 * * * *' for hourly)")
    @click.option("--interval", help="Interval schedule (e.g., '1h', '30m', '1d')")
    @click.option("--timezone", default="UTC", help="Timezone for schedule (default: UTC)")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_add(
        custom_id,
        replace_id,
        name,
        rule_file,
        conditions,
        action_ids,
        description,
        cron,
        interval,
        timezone,
        fmt,
    ):
        """Add or replace a rule with DSL conditions and optional schedule.

        Examples:
            monitor setup rule-add --name "Tech Videos" \\
                --conditions "content_type == 'video' and extra.theme == 'tech'" \\
                --action-ids notify

            monitor setup rule-add --name "Hourly Check" \\
                --conditions "source_metadata.priority == 'high'" \\
                --cron "0 * * * *" \\
                --action-ids notify

            monitor setup rule-add --name "Every 5 Minutes" \\
                --conditions "extra.views > 1000" \\
                --interval "5m" \\
                --action-ids notify
        """
        storage = get_storage()
        parser = RuleParser()

        if rule_file:
            with open(rule_file) as f:
                if rule_file.endswith(".json"):
                    conditions_data = json.load(f)
                else:
                    yaml_data = yaml.safe_load(f)
                    if "conditions" in yaml_data and isinstance(yaml_data["conditions"], str):
                        try:
                            conditions_data = parser.parse(yaml_data["conditions"])
                        except RuleParseError as e:
                            out_formatted({"error": f"Invalid DSL in rule file: {e}"}, fmt)
                            return
                    else:
                        conditions_data = yaml_data
        elif conditions:
            try:
                conditions_data = parser.parse(conditions)
            except RuleParseError as e:
                out_formatted({"error": f"Invalid DSL conditions: {e}"}, fmt)
                return
        else:
            out_formatted({"error": "Either --rule-file or --conditions required"}, fmt)
            return

        schedule = None
        if cron:
            if not validate_cron_expression(cron):
                out_formatted({"error": f"Invalid cron expression: {cron}"}, fmt)
                return
            schedule = {"cron": cron}
        elif interval:
            if not validate_interval_expression(interval):
                out_formatted(
                    {
                        "error": f"Invalid interval expression: {interval}. Expected format: <number><unit> (e.g., '1h', '30m', '1d')"
                    },
                    fmt,
                )
                return
            schedule = {"interval": interval}

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
            existing.schedule = schedule
            existing.timezone = timezone
            storage.update_rule(existing)
            out_formatted({"id": replace_id, "message": "Rule replaced", "schedule": schedule}, fmt)
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
            schedule=schedule,
            timezone=timezone,
        )

        storage.add_rule(rule)
        formatter = RuleFormatter()
        dsl_conditions = formatter.format(rule.conditions)
        out_formatted(
            {
                "id": rule.id,
                "name": rule.name,
                "conditions_dsl": dsl_conditions,
                "action_ids": rule.action_ids,
                "schedule": schedule,
                "timezone": timezone,
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
        formatter = RuleFormatter()
        out_formatted(
            [
                {
                    "id": r.id,
                    "name": r.name,
                    "conditions_dsl": formatter.format(r.conditions),
                    "conditions": r.conditions,
                    "action_ids": r.action_ids,
                    "schedule": r.schedule,
                    "timezone": r.timezone,
                    "description": r.description,
                    "last_triggered_at": r.last_triggered_at.isoformat()
                    if r.last_triggered_at
                    else None,
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
    @click.option(
        "-i",
        "--interactive",
        "interactive",
        is_flag=True,
        help="Open interactive editor with DSL format",
    )
    @click.option("--name", help="New rule name")
    @click.option(
        "--rule-file",
        type=click.Path(exists=True),
        help="YAML/JSON file with new rule conditions",
    )
    @click.option(
        "--conditions",
        help="DSL condition string (e.g., \"content_type == 'video' and duration > 600\")",
    )
    @click.option("--action-ids", help="Comma-separated action IDs")
    @click.option("--description", help="New description")
    @click.option("--enable/--disable", default=None, help="Enable or disable rule")
    @click.option("--cron", help="Cron schedule (e.g., '0 * * * *' for hourly)")
    @click.option("--interval", help="Interval schedule (e.g., '1h', '30m', '1d')")
    @click.option("--timezone", help="Timezone for schedule")
    @click.option("--no-schedule", is_flag=True, help="Remove schedule from rule")
    @click.option("--editor", help="Editor to use (default: $EDITOR or nano)")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_edit(
        rule_id,
        interactive,
        name,
        rule_file,
        conditions,
        action_ids,
        description,
        enable,
        cron,
        interval,
        timezone,
        no_schedule,
        editor,
        fmt,
    ):
        """Edit an existing rule interactively or with options.

        Use -i/--interactive to open the editor with DSL format.

        Examples:
            monitor setup rule-edit my-rule -i  # Interactive editor
            monitor setup rule-edit my-rule --name "New Name"
            monitor setup rule-edit my-rule --conditions "content_type == 'video'"
            monitor setup rule-edit my-rule --cron "0 6 * * *"
            monitor setup rule-edit my-rule --no-schedule
        """
        storage = get_storage()
        parser = RuleParser()
        formatter = RuleFormatter()
        existing = storage.get_rule(rule_id)
        if not existing:
            out_formatted({"error": f"Rule {rule_id} not found"}, fmt)
            return

        if interactive:
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_rule_edit(existing, parser, formatter, storage, editor_cmd, fmt)
            return
        elif (
            name is None
            and not rule_file
            and not conditions
            and not action_ids
            and not description
            and enable is None
            and not cron
            and not interval
            and not timezone
            and not no_schedule
        ):
            editor_cmd = editor or os.environ.get("EDITOR", "nano")
            _interactive_rule_edit(existing, parser, formatter, storage, editor_cmd, fmt)
            return

        if name is not None:
            existing.name = name

        if rule_file:
            with open(rule_file) as f:
                if rule_file.endswith(".json"):
                    existing.conditions = json.load(f)
                else:
                    yaml_data = yaml.safe_load(f)
                    if "conditions" in yaml_data and isinstance(yaml_data["conditions"], str):
                        try:
                            existing.conditions = parser.parse(yaml_data["conditions"])
                        except RuleParseError as e:
                            out_formatted({"error": f"Invalid DSL in rule file: {e}"}, fmt)
                            return
                    else:
                        existing.conditions = yaml_data
        elif conditions:
            try:
                existing.conditions = parser.parse(conditions)
            except RuleParseError as e:
                out_formatted({"error": f"Invalid DSL conditions: {e}"}, fmt)
                return

        if action_ids is not None:
            existing.action_ids = [aid.strip() for aid in action_ids.split(",")]

        if description is not None:
            existing.description = description

        if enable is not None:
            existing.enabled = enable

        if no_schedule:
            existing.schedule = None
        elif cron:
            if not validate_cron_expression(cron):
                out_formatted({"error": f"Invalid cron expression: {cron}"}, fmt)
                return
            existing.schedule = {"cron": cron}
        elif interval:
            if not validate_interval_expression(interval):
                out_formatted({"error": f"Invalid interval expression: {interval}"}, fmt)
                return
            existing.schedule = {"interval": interval}

        if timezone is not None:
            existing.timezone = timezone

        storage.update_rule(existing)
        formatter = RuleFormatter()
        out_formatted(
            {
                "id": existing.id,
                "message": "Rule updated",
                "rule": {
                    "id": existing.id,
                    "name": existing.name,
                    "conditions_dsl": formatter.format(existing.conditions),
                    "action_ids": existing.action_ids,
                    "schedule": existing.schedule,
                    "timezone": existing.timezone,
                    "description": existing.description,
                },
            },
            fmt,
        )

    @setup_group.command("rule-validate")
    @click.argument("condition_string")
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    def rule_validate(condition_string, fmt):
        """Validate a condition DSL string without saving.

        Examples:
            monitor setup rule-validate "content_type == 'video'"
            monitor setup rule-validate "(source_plugin == 'youtube' and content_type == 'video') or source_metadata.priority == 'high'"
        """
        parser = RuleParser()
        formatter = RuleFormatter()
        try:
            result = parser.parse(condition_string)
            click.echo("Valid condition string")
            click.echo(f"\nParsed DSL (normalized):")
            click.echo(formatter.format(result))
            click.echo(f"\nInternal format:")
            out_formatted(result, fmt)
        except RuleParseError as e:
            out_formatted({"error": f"Invalid DSL: {e}"}, fmt)

    @setup_group.command("rule-show")
    @click.argument("rule_id")
    @click.option("--format", type=click.Choice(["dsl", "json", "yaml"]), default="dsl")
    def rule_show(rule_id, format):
        """Show a rule in human-readable format.

        Examples:
            monitor setup rule-show my-rule
            monitor setup rule-show my-rule --format json
        """
        storage = get_storage()
        rule = storage.get_rule(rule_id)
        if not rule:
            click.echo(f"Error: Rule {rule_id} not found", err=True)
            return

        formatter = RuleFormatter()

        if format == "json":
            output = {
                "id": rule.id,
                "name": rule.name,
                "conditions": rule.conditions,
                "conditions_dsl": formatter.format(rule.conditions),
                "action_ids": rule.action_ids,
                "schedule": rule.schedule,
                "timezone": rule.timezone,
                "enabled": rule.enabled,
                "description": rule.description,
                "created_at": rule.created_at.isoformat(),
                "last_triggered_at": rule.last_triggered_at.isoformat()
                if rule.last_triggered_at
                else None,
            }
            click.echo(json.dumps(output, indent=2))
        elif format == "yaml":
            output = {
                "id": rule.id,
                "name": rule.name,
                "conditions": formatter.format(rule.conditions),
                "action_ids": rule.action_ids,
                "schedule": rule.schedule,
                "timezone": rule.timezone,
                "enabled": rule.enabled,
                "description": rule.description,
                "created_at": rule.created_at.isoformat(),
                "last_triggered_at": rule.last_triggered_at.isoformat()
                if rule.last_triggered_at
                else None,
            }
            click.echo(yaml.dump(output, default_flow_style=False, sort_keys=False))
        else:
            schedule_str = ""
            if rule.schedule:
                if "cron" in rule.schedule:
                    schedule_str = f"  schedule:\n    cron: {rule.schedule['cron']}"
                elif "interval" in rule.schedule:
                    schedule_str = f"  schedule:\n    interval: {rule.schedule['interval']}"

            click.echo(f"id: {rule.id}")
            click.echo(f"name: {rule.name}")
            if rule.description:
                click.echo(f"description: {rule.description}")
            click.echo(f"enabled: {rule.enabled}")
            click.echo(f"actions: {rule.action_ids}")
            click.echo(f"timezone: {rule.timezone}")
            if schedule_str:
                click.echo(schedule_str)
            click.echo(f"conditions: |")
            dsl = formatter.format(rule.conditions, pretty=True)
            for line in dsl.split("\n"):
                click.echo(f"  {line}")
            if rule.last_triggered_at:
                click.echo(f"last_triggered_at: {rule.last_triggered_at.isoformat()}")

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
