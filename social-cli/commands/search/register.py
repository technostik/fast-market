"""Search command — search posts on social backends."""

from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_plugin, load_config, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("search")
    @click.argument("query")
    @click.option(
        "--backend",
        "-b",
        "backend",
        type=click.Choice(source_choices),
        default="twitter",
        help="Social backend to search.",
    )
    @click.option(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Maximum number of results to return.",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format.",
    )
    @click.option(
        "--language",
        default="en",
        help="Language filter for search.",
    )
    @click.pass_context
    def search_cmd(ctx, query, backend, limit, fmt, language, **kwargs):
        try:
            config = load_config()
        except Exception as e:
            raise click.ClickException(str(e))
        plugin = build_plugin(config, backend)

        try:
            results = plugin.search(query, max_results=limit, language=language)
            out({"backend": backend, "query": query, "count": len(results), "results": results}, fmt)
        except NotImplementedError as e:
            out({"status": "error", "error": str(e), "backend": backend}, fmt)
            raise SystemExit(1)
        except Exception as e:
            out({"status": "error", "error": str(e), "backend": backend}, fmt)
            raise SystemExit(1)

    # Inject plugin-specific options
    for pm in plugin_manifests.values():
        search_cmd.params.extend(pm.cli_options.get("search", []))

    return CommandManifest(
        name="search",
        click_command=search_cmd,
    )
