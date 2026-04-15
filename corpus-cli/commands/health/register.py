from __future__ import annotations

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command(
        "health",
        help="Check corpus health and diagnose issues (supports --source youtube).",
    )
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default=None,
        help="Check health for specific source",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.pass_context
    def health_cmd(ctx, source, fmt, **kwargs):
        from common.core.config import load_config
        from common.core.registry import build_plugins
        from storage.sqlite_store import SQLiteStore
        from pathlib import Path

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        plugins = build_plugins(config, tool_root=Path(__file__).resolve().parents[2])

        results = []

        # If checking YouTube specifically
        if source == "youtube" or (source is None and "youtube" in plugins):
            youtube_result = _check_youtube_health(config, store, plugins)
            results.append(youtube_result)

        # If checking other sources or all sources
        if source and source != "youtube":
            if source in plugins:
                result = _check_source_health(source, store, plugins[source])
                results.append(result)
            else:
                raise click.ClickException(f"Unknown source: {source}")
        elif source is None:
            # Check all non-YouTube sources
            for name, plugin in plugins.items():
                if name != "youtube":
                    result = _check_source_health(name, store, plugin)
                    results.append(result)

        if fmt == "text":
            for result in results:
                _print_health_text(result)
                click.echo()
        else:
            out(results, fmt)

    return CommandManifest(
        name="health",
        click_command=health_cmd,
        api_router=_build_router(source_choices),
    )


def _check_youtube_health(config, store, plugins) -> dict:
    """Check YouTube source health and diagnose issues."""
    from common.youtube.client import YouTubeClient

    result = {
        "source": "youtube",
        "status": "ok",
        "issues": [],
        "recommendations": [],
    }

    try:
        youtube_plugin = plugins["youtube"]
    except KeyError:
        result["status"] = "error"
        result["issues"].append("YouTube plugin not configured")
        return result

    # Get indexed documents count
    status = store.status()
    youtube_status = next((s for s in status if s["source_plugin"] == "youtube"), None)
    indexed_count = youtube_status["docs"] if youtube_status else 0

    # Get failures
    failures = store.list_failures("youtube")
    permanent_failures = [f for f in failures if f.get("error_type") == "permanent"]
    transient_failures = [f for f in failures if f.get("error_type") == "transient"]

    result["indexed_count"] = indexed_count
    result["permanent_failures"] = len(permanent_failures)
    result["transient_failures"] = len(transient_failures)

    # Fetch YouTube stats
    try:
        max_fetch = 999999
        all_videos = youtube_plugin.list_items(limit=max_fetch, use_api=True)

        by_privacy = {}
        for item in all_videos:
            privacy = item.metadata.get("privacy_status", "unknown")
            by_privacy[privacy] = by_privacy.get(privacy, 0) + 1

        fetched_count = len(all_videos)
        result["fetched_count"] = fetched_count
        result["by_privacy"] = by_privacy

        # Check for unlisted videos not being indexed
        unlisted_count = by_privacy.get("unlisted", 0)
        public_count = by_privacy.get("public", 0)

        # Get channel total
        client = youtube_plugin._get_api_client()
        channel_info = client.get_channel_info(youtube_plugin.channel_id)
        total_videos = channel_info.video_count if channel_info else fetched_count
        result["total_videos"] = total_videos

        # Diagnose issues
        missing_count = total_videos - fetched_count
        if missing_count > 0:
            result["issues"].append(
                f"{missing_count} videos not fetched (out of {total_videos} total)"
            )
            if unlisted_count > 0:
                result["issues"].append(
                    f"{unlisted_count} unlisted videos detected (may require index_non_public config)"
                )
                result["recommendations"].append(
                    "Set youtube.index_non_public: true in config to index unlisted videos"
                )

        if permanent_failures:
            result["issues"].append(
                f"{len(permanent_failures)} permanent failure(s) - videos that failed to sync"
            )
            result["recommendations"].append(
                "Run `corpus sync --source youtube --retry-failure --clear-permanent` to retry"
            )

        if transient_failures:
            result["issues"].append(
                f"{len(transient_failures)} transient failure(s) - temporary errors"
            )
            result["recommendations"].append(
                "Run `corpus sync --source youtube --retry-failure` to retry"
            )

        if indexed_count != public_count:
            result["issues"].append(
                f"Indexed count ({indexed_count}) doesn't match fetched public videos ({public_count})"
            )

        # Determine overall status
        if result["issues"]:
            result["status"] = "warning"
            if permanent_failures or missing_count > total_videos * 0.1:
                result["status"] = "error"

    except Exception as e:
        result["status"] = "error"
        result["issues"].append(f"Failed to fetch YouTube stats: {str(e)}")

    return result


def _check_source_health(source_name, store, plugin) -> dict:
    """Check health for non-YouTube sources."""
    result = {
        "source": source_name,
        "status": "ok",
        "issues": [],
        "recommendations": [],
    }

    try:
        status = store.status()
        source_status = next(
            (s for s in status if s["source_plugin"] == source_name), None
        )

        indexed_count = source_status["docs"] if source_status else 0
        permanent_failures = source_status.get("sync_failures_permanent", 0)
        transient_failures = source_status.get("sync_failures_transient", 0)

        result["indexed_count"] = indexed_count
        result["permanent_failures"] = permanent_failures
        result["transient_failures"] = transient_failures

        if permanent_failures > 0:
            result["issues"].append(f"{permanent_failures} permanent failure(s)")
            result["recommendations"].append(
                f"Run `corpus sync --source {source_name} --retry-failure --clear-permanent`"
            )

        if transient_failures > 0:
            result["issues"].append(f"{transient_failures} transient failure(s)")
            result["recommendations"].append(
                f"Run `corpus sync --source {source_name} --retry-failure`"
            )

        if indexed_count == 0:
            result["issues"].append("No documents indexed")
            result["recommendations"].append(f"Run `corpus sync --source {source_name}`")

        if result["issues"]:
            result["status"] = "warning"

    except Exception as e:
        result["status"] = "error"
        result["issues"].append(f"Failed to check health: {str(e)}")

    return result


def _print_health_text(result: dict) -> None:
    """Print health result in text format."""
    click.echo(f"source: {result['source']}")
    click.echo(f"status: {result['status']}")

    if "indexed_count" in result:
        click.echo(f"  indexed: {result['indexed_count']}")

    if "fetched_count" in result:
        click.echo(f"  fetched: {result['fetched_count']}")

    if "total_videos" in result:
        click.echo(f"  total: {result['total_videos']}")

    if "by_privacy" in result:
        click.echo(f"  by_privacy: {result['by_privacy']}")

    if result.get("permanent_failures", 0) > 0:
        click.echo(f"  permanent_failures: {result['permanent_failures']}")

    if result.get("transient_failures", 0) > 0:
        click.echo(f"  transient_failures: {result['transient_failures']}")

    if result["issues"]:
        click.echo("  issues:")
        for issue in result["issues"]:
            click.echo(f"    - {issue}")

    if result["recommendations"]:
        click.echo("  recommendations:")
        for rec in result["recommendations"]:
            click.echo(f"    - {rec}")


def _build_router(source_choices: list[str]) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health(source: str = None):
        from common.core.config import load_config
        from common.core.registry import build_plugins
        from storage.sqlite_store import SQLiteStore
        from pathlib import Path

        config = load_config()
        store = SQLiteStore(config.get("db_path"))
        plugins = build_plugins(config, tool_root=Path(__file__).resolve().parents[2])

        results = []

        if source:
            if source not in source_choices:
                raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
            if source == "youtube":
                result = _check_youtube_health(config, store, plugins)
                results.append(result)
            else:
                result = _check_source_health(source, store, plugins.get(source))
                results.append(result)
        else:
            if "youtube" in plugins:
                result = _check_youtube_health(config, store, plugins)
                results.append(result)
            for name, plugin in plugins.items():
                if name != "youtube":
                    result = _check_source_health(name, store, plugin)
                    results.append(result)

        return results

    return router
