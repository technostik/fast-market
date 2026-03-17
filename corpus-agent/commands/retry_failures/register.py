from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out

_DEFAULT_LIMITS = {"youtube": 5}
_FALLBACK_LIMIT = 10


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys()) + ["all"]

    @click.command("retry-failures")
    @click.option("--source", type=click.Choice(source_choices), default="all")
    @click.option("--clear-permanent", is_flag=True, default=False, help="Also retry permanent failures")
    @click.option("--limit", type=int, default=None)
    @click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
    @click.pass_context
    def retry_failures_cmd(ctx, source, clear_permanent, limit, fmt):
        engine, plugins, store = build_engine(ctx.obj["verbose"])
        targets = list(plugins.keys()) if source == "all" else [source]
        results = []
        for name in targets:
            removed = store.clear_failures(name, include_permanent=clear_permanent)
            effective_limit = limit if limit is not None else _DEFAULT_LIMITS.get(name, _FALLBACK_LIMIT)
            result = engine.sync(plugins[name], mode="new", limit=effective_limit)
            results.append({
                "source": result.source,
                "cleared_failures": removed,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "failures": len(result.failures),
            })
        out(results, fmt)

    return CommandManifest(name="retry-failures", click_command=retry_failures_cmd)
