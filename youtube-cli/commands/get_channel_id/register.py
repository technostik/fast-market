from __future__ import annotations

from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.common.channel_search import search_channels, format_channel_entry, select_channel_interactive
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get-channel-id")
    @click.argument("query", required=False)
    @click.option("--max-results", "-n", type=int, default=10, help="Max channels to search (default: 10)")
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format (default: text)",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option("--auto", "-a", is_flag=True, help="Auto-select first result (no interactive prompt)")
    def get_channel_id_cmd(query, max_results, fmt, output, auto):
        """Search for a YouTube channel and return its ID.

        Given a search string, displays possible channels, lets the user
        choose, and returns the channel ID and title.

        Output formats: text (default), yaml, json

        Examples:
            youtube get-channel-id "Johann Norel"
            youtube get-channel-id "Tech channel" -f yaml
            youtube get-channel-id "Gaming" -f json -o channels.json
            youtube get-channel-id "Music" --auto -f yaml
        """
        if not query:
            query = input("Search for a channel (name/keyword): ").strip()
            if not query:
                raise click.ClickException("No search query provided.")

        click.echo(f"\nSearching for channels matching '{query}'...")

        try:
            results = search_channels(query, max_results)
        except RuntimeError as e:
            raise click.ClickException(str(e)) from e

        if not results:
            raise click.ClickException("No channels found.")

        if auto:
            selected = results[0]
        else:
            try:
                selected = select_channel_interactive(results)
            except click.ClickException:
                raise
            except KeyboardInterrupt:
                raise click.ClickException("Cancelled.")

        # Build output: always includes id and title
        result = {
            "id": selected["channel_id"],
            "title": selected["title"],
        }
        # Include extra fields if available
        if selected.get("custom_url"):
            result["custom_url"] = selected["custom_url"]
        if selected.get("subscriber_count"):
            result["subscriber_count"] = selected["subscriber_count"]
        if selected.get("description"):
            result["description"] = selected["description"]

        if output:
            Path(output).write_text(
                yaml.dump(result, default_flow_style=False, sort_keys=False, allow_unicode=True)
                if fmt in ("yaml", "text")
                else __import__("json").dumps(result, ensure_ascii=False, default=str)
            )
            click.echo(f"Saved to {output}")
        else:
            out(result, fmt)

    return CommandManifest(
        name="get-channel-id",
        click_command=get_channel_id_cmd,
    )
