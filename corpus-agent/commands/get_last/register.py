from __future__ import annotations

import sys

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out

_DEFAULT_LIMITS = {"youtube": 5}
_FALLBACK_LIMIT = 10


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command(
        "get-last",
        help="Sync sources and retrieve the most recently indexed documents.",
    )
    @click.option(
        "--limit",
        "-l",
        type=int,
        default=1,
        show_default=True,
        help="Number of recent items to retrieve.",
    )
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default=None,
        help="Filter by source plugin.",
    )
    @click.option(
        "--what",
        type=click.Choice(["meta", "content", "all"]),
        default="content",
        show_default=True,
        help="What to display: meta (metadata only), content (text only), all (both).",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        show_default=True,
        help="Output format.",
    )
    @click.pass_context
    def get_last_cmd(ctx, limit, source, what, fmt, **kwargs):
        from common.core.config import load_config

        engine, plugins, store = build_engine(ctx.obj["verbose"])
        config = load_config()
        obsidian_vault_path = config.get("obsidian", {}).get("vault_path")
        targets = (
            list(plugins.keys()) if source == "all" or source is None else [source]
        )
        for name in targets:
            effective_limit = limit
            vault_path = obsidian_vault_path if name == "obsidian" else None
            result = engine.sync(
                plugins[name], mode="new", limit=effective_limit, vault_path=vault_path
            )

        docs = store.list_documents_extended(
            source=source,
            filters=None,
            order_by="date",
            reverse=False,
            limit=limit,
        )

        if not docs:
            return

        for doc in docs:
            _print_doc(doc, what, fmt)

    return CommandManifest(name="get-last", click_command=get_last_cmd)


def _print_doc(doc: dict, what: str, fmt: str) -> None:
    if what == "content":
        click.echo(doc.get("raw_text", ""))
        return

    if what == "meta":
        meta = {k: v for k, v in doc.items() if k != "raw_text"}
        out(meta, fmt)
        return

    if fmt == "json":
        out(doc, fmt)
    else:
        for key, value in doc.items():
            if key == "raw_text":
                click.echo(f"\n--- content ({len(value)} chars) ---\n")
                click.echo(value)
            else:
                click.echo(f"  {key}: {value}")
