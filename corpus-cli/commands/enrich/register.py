from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from core.pool_rows import NOT_SYNCED_STATES

_STATE_CHOICES = ["not-synced", *NOT_SYNCED_STATES]


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())
    # Enrichment fetches video metadata via yt-dlp; default to the YouTube
    # plugin when present so `corpus enrich` works with zero flags.
    default_source = "youtube" if "youtube" in plugin_manifests else None

    @click.command(
        "enrich",
        help=(
            "Bulk-fetch metadata for non-synced (pool) items using yt-dlp.\n\n"
            "For each scanned-but-not-indexed YouTube video this fills missing "
            "metadata (duration, view/like counts, tags, chapters, ...) directly "
            "from yt-dlp — no YouTube API quota involved. Metadata is written "
            "back to the pool so it shows up in `corpus list` and the webux "
            "Corpus Browser without re-scanning."
        ),
    )
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default=default_source,
        help="Source plugin whose pool items to enrich (default: youtube).",
    )
    @click.option(
        "--state",
        type=click.Choice(_STATE_CHOICES),
        default="not-synced",
        help="Pool states to enrich: not-synced (default) covers pending, failed "
             "and excluded items.",
    )
    @click.option(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Max items to enrich (default: all matching).",
    )
    @click.option(
        "--concurrency",
        "-c",
        type=int,
        default=4,
        help="Parallel yt-dlp workers (default: 4).",
    )
    @click.option(
        "--handles",
        "handles",
        multiple=True,
        default=None,
        help="Restrict to specific pool handles (e.g. pool:youtube:<id>, repeatable).",
    )
    @click.option(
        "--cookies",
        type=click.Path(exists=True),
        default=None,
        help="Path to a cookies.txt for yt-dlp (defaults to youtube.cookies in config).",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.option("--silent", "-s", is_flag=True, default=False)
    @click.pass_context
    def enrich_cmd(ctx, source, state, limit, concurrency, handles, cookies, fmt, silent, **kwargs):
        verbose = ctx.obj.get("verbose", True) and not silent
        _engine, _plugins, store = build_engine(verbose)

        if not source:
            raise click.UsageError(
                "No YouTube plugin found to default to. Pass --source from: "
                + ", ".join(sorted(source_choices))
            )

        if handles:
            source_ids = [
                h.split(":", 2)[2] for h in handles if h.startswith(f"pool:{source}:")
            ]
        else:
            source_ids = _select_pool_ids(store, source, state)

        from core.pool_enrich import enrich_pool_items

        result = enrich_pool_items(
            store,
            source,
            source_ids=source_ids,
            cookies=cookies,
            concurrency=concurrency,
            limit=limit,
        )
        if verbose:
            _echo_progress(result)
        out(result.to_dict(), fmt)
        if result.failed:
            ctx.exit(1)

    return CommandManifest(name="enrich", click_command=enrich_cmd)


def _select_pool_ids(store, name: str, state: str) -> list[str]:
    """Pool source_ids for one plugin matching the requested state filter."""
    items = store.get_pool_items(name, status=None)
    if state == "not-synced":
        items = [i for i in items if i["status"] in NOT_SYNCED_STATES]
    else:
        items = [i for i in items if i["status"] == state]
    return [i["source_id"] for i in items]


def _echo_progress(result) -> None:
    click.echo(
        f"{result.source}: {result.enriched} enriched · {result.skipped} unchanged "
        f"· {result.failed} failed ({result.processed} attempted)",
        err=True,
    )
