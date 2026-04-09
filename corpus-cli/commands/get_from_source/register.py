from __future__ import annotations

import re
import sys
from datetime import datetime

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from common.core.duration import parse_iso_duration
from core.sync_errors import APIRateLimitError, NetworkError, TranscriptUnavailableError
from plugins.base import ItemMeta

_YOUTUBE_URL_PATTERNS = [
    r"youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})",
    r"youtu\.be/([a-zA-Z0-9_-]{11})",
    r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    r"youtube\.com/v/([a-zA-Z0-9_-]{11})",
]
_YOUTUBE_URL_RE = re.compile("|".join(_YOUTUBE_URL_PATTERNS))
_BARE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def _extract_youtube_id(id_input: str) -> str | None:
    match = _YOUTUBE_URL_RE.search(id_input)
    if match:
        return match.group(1)
    if _BARE_VIDEO_ID_RE.match(id_input):
        return id_input
    return None


def _detect_source(id_input: str, plugin_manifests: dict) -> str | None:
    if _extract_youtube_id(id_input):
        if "youtube" in plugin_manifests:
            return "youtube"
    if "/" in id_input or id_input.endswith(".md"):
        if "obsidian" in plugin_manifests:
            return "obsidian"
    if len(plugin_manifests) == 1:
        return next(iter(plugin_manifests.keys()))
    return None


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("get-from-source")
    @click.argument(
        "source", type=click.Choice(source_choices), required=False, default=None
    )
    @click.argument("id")
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
    def get_from_source_cmd(ctx, source, id, what, fmt, **kwargs):
        """Retrieve a document by source and ID, auto-syncing if not already indexed.

        Source is auto-detected from the ID if not provided:
        - YouTube URLs or 11-char IDs → youtube
        - File paths (contains / or ends with .md) → obsidian

        Supports flexible ID formats:

        \b
        YouTube: video ID (e.g., dQw4w9WgXcQ) or full URL
                (youtube.com/watch?v=, youtu.be/, /embed/, /shorts/)
        Obsidian: vault-relative path (e.g., notes/foo.md)
        """
        engine, plugins, store = build_engine(ctx.obj["verbose"])

        if source is None:
            source = _detect_source(id, plugin_manifests)
            if source is None:
                click.echo(
                    f"Could not auto-detect source for: {id}\n"
                    f"Available sources: {', '.join(plugin_manifests.keys())}",
                    err=True,
                )
                sys.exit(1)

        plugin = plugins[source]

        if source == "youtube":
            source_id = _extract_youtube_id(id)
            if not source_id:
                click.echo(f"Invalid YouTube URL or video ID: {id}", err=True)
                sys.exit(1)
        else:
            source_id = id

        existing = store.get_document(source, source_id)
        if existing:
            _print_doc(existing, what, fmt)
            return

        if source == "youtube":
            _sync_youtube(plugin, source_id, engine, store)
        else:
            _sync_generic(plugin, source_id, engine, store)

        doc = store.get_document(source, source_id)
        if not doc:
            click.echo(f"Failed to sync: {source}:{source_id}", err=True)
            sys.exit(1)
        _print_doc(doc, what, fmt)

    return CommandManifest(name="get-from-source", click_command=get_from_source_cmd)


def _sync_youtube(plugin, video_id: str, engine, store) -> None:
    try:
        details = plugin.transport.get_video_details([video_id])
        if video_id not in details:
            click.echo(f"Video not found or unavailable: {video_id}", err=True)
            sys.exit(1)
        detail = details[video_id]
        snippet = detail.get("snippet", {})
        published_at = snippet.get("publishedAt", "")
        if published_at:
            updated = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        else:
            updated = datetime.utcnow()
        duration = parse_iso_duration(detail.get("contentDetails", {}).get("duration", 0))
        item_meta = ItemMeta(
            source_id=video_id,
            updated_at=updated,
            metadata={
                "id": video_id,
                "title": snippet.get("title", video_id),
                "description": snippet.get("description", ""),
                "published_at": published_at,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "duration_seconds": duration,
                "privacy_status": detail.get("status", {}).get(
                    "privacyStatus", "unknown"
                ),
            },
        )
        document = plugin.fetch(item_meta)
        _store_document(document, engine, store)
    except APIRateLimitError as exc:
        click.echo(f"YouTube API rate limit exceeded. Try again later.", err=True)
        sys.exit(1)
    except NetworkError as exc:
        click.echo(f"Network error fetching YouTube video {video_id}: {exc}", err=True)
        sys.exit(1)
    except TranscriptUnavailableError as exc:
        click.echo(f"No transcript available for video {video_id}.", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error syncing YouTube video {video_id}: {exc}", err=True)
        sys.exit(1)


def _sync_generic(plugin, source_id: str, engine, store) -> None:
    try:
        item_meta = ItemMeta(source_id=source_id)
        document = plugin.fetch(item_meta)
        _store_document(document, engine, store)
    except FileNotFoundError as exc:
        click.echo(f"Note not found: {source_id}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error syncing {source_id}: {exc}", err=True)
        sys.exit(1)


def _store_document(document, engine, store) -> None:
    from core.handle import make_handle

    document.handle = make_handle(
        document.source_plugin, document.source_id, document.title
    )
    content_hash = engine.embedder.hash_text(document.raw_text)
    store.upsert_document(document, content_hash)
    chunks = engine._build_chunks(document)
    store.replace_chunks(document.source_plugin, document.source_id, chunks)
    store.clear_failure(document.source_plugin, document.source_id)


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
