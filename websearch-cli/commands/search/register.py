from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_providers, out
from commands.completion import SourceParamType
from common.core.config import load_tool_config
from common import structlog

logger = structlog.get_logger(__name__)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "search",
        help="Search the web. Bare `websearch \"<query>\"` routes here.",
    )
    @click.argument("query")
    @click.option(
        "--source",
        "-s",
        type=SourceParamType(),
        default="all",
        help="Provider to search (default: all).",
    )
    @click.option("--limit", "-l", type=int, default=None, help="Max items per provider.")
    @click.option("--language", "-L", default=None, help="Language (drives google_news hl/gl).")
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="json",
        help="Output format (default: json).",
    )
    @click.pass_context
    def search_cmd(ctx, query, source, limit, language, fmt, **kwargs):
        config = load_tool_config("websearch")
        limit = limit if limit is not None else int(config.get("limit", 10))
        language = language or config.get("language", "fr")

        providers = build_providers(config)
        targets = list(providers.keys()) if source == "all" else [source]

        results = []
        errors = 0
        for name in targets:
            provider = providers.get(name)
            if provider is None:
                click.echo(f"warning: unknown source '{name}'", err=True)
                continue
            try:
                results.extend(provider.search(query, limit, language=language, **kwargs))
            except Exception as exc:
                errors += 1
                logger.warning("provider_search_failed", source=name, error=str(exc))
                click.echo(f"warning: {name} search failed: {exc}", err=True)

        if not results:
            if errors:
                ctx.exit(1)
            click.echo("no results", err=True)
            return

        out(
            [
                {
                    "url": r.url,
                    "title": r.title,
                    "description": r.description,
                    "source": r.source,
                }
                for r in results
            ],
            fmt,
        )

    for pm in plugin_manifests.values():
        search_cmd.params.extend(pm.cli_options.get("search", []))

    return CommandManifest(name="search", click_command=search_cmd)
