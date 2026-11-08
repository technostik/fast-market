from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import build_engine, out
from core.models import Document


def _read_text(value: str | None, path: str | None, label: str) -> str:
    """Return inline text, or the contents of ``path``. Both are optional."""
    if value is not None and path is not None:
        raise click.ClickException(f"Use either --{label} or --{label}-file, not both.")
    if path:
        try:
            return Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Cannot read --{label}-file {path}: {exc}") from exc
    return value or ""


def _parse_published_at(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise click.ClickException(
            f"Invalid --published-at {text!r}: expected ISO 8601 (e.g. 2026-11-06T18:00:00Z)."
        ) from exc


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())
    default_source = "youtube" if "youtube" in source_choices else source_choices[0]

    @click.command(
        "add",
        help=(
            "Index one document whose content is already known.\n\n"
            "No plugin fetch, no API quota: the transcript is taken as-is and "
            "the description is stored in metadata (like a YouTube sync does). "
            "The document is marked synced in the pool so later scans skip it."
        ),
    )
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default=default_source,
        show_default=True,
        help="Source plugin the document belongs to.",
    )
    @click.option("--id", "source_id", required=True, help="Source ID (YouTube video ID).")
    @click.option("--url", required=True, help="Public URL of the document.")
    @click.option("--title", required=True, help="Document title.")
    @click.option(
        "--transcript",
        default=None,
        help="Transcript text (inline). Mutually exclusive with --transcript-file.",
    )
    @click.option(
        "--transcript-file",
        default=None,
        help="File containing the transcript. Mutually exclusive with --transcript.",
    )
    @click.option(
        "--description",
        default=None,
        help="Description text (inline). Mutually exclusive with --description-file.",
    )
    @click.option(
        "--description-file",
        default=None,
        help="File containing the description. Mutually exclusive with --description.",
    )
    @click.option(
        "--privacy",
        default="unknown",
        show_default=True,
        help="Privacy status (YouTube: public|unlisted|private|members).",
    )
    @click.option(
        "--duration",
        type=int,
        default=0,
        show_default=True,
        help="Duration in seconds (0 = unknown).",
    )
    @click.option(
        "--published-at",
        default="",
        help="ISO 8601 publish date (defaults to now).",
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
    def add_cmd(
        ctx,
        source: str,
        source_id: str,
        url: str,
        title: str,
        transcript: str | None,
        transcript_file: str | None,
        description: str | None,
        description_file: str | None,
        privacy: str,
        duration: int,
        published_at: str,
        fmt: str,
    ):
        if not source_id.strip():
            raise click.ClickException("--id must not be empty.")
        if not title.strip():
            raise click.ClickException("--title must not be empty.")
        if not url.strip():
            raise click.ClickException("--url must not be empty.")

        transcript_text = _read_text(transcript, transcript_file, "transcript").strip()
        if not transcript_text:
            raise click.ClickException(
                "Transcript is empty; refusing to index a document without content."
            )
        description_text = _read_text(description, description_file, "description").strip()

        updated_at = _parse_published_at(published_at) or datetime.now()
        duration_seconds = max(0, duration)
        from common.core.profile import resolve_profile

        # Profile at insert time: explicit --profile on the corpus group exports
        # FASTMARKET_PROFILE; the publish pipelines pass it on the subprocess env.
        profile = resolve_profile()
        metadata = {
            "id": source_id,
            "title": title,
            "description": description_text,
            "published_at": published_at.strip() or updated_at.isoformat(),
            "url": url,
            "duration_seconds": duration_seconds,
            "privacy_status": privacy or "unknown",
            "profile": profile,
        }

        document = Document(
            source_plugin=source,
            source_id=source_id,
            title=title,
            raw_text=transcript_text,
            profile=profile,
            url=url,
            updated_at=updated_at,
            duration_seconds=duration_seconds or None,
            privacy_status=privacy or "unknown",
            metadata=metadata,
        )

        verbose = ctx.obj.get("verbose", True) if ctx.obj else True
        engine, _plugins, _store = build_engine(verbose)
        result = engine.add_document(document)
        result["url"] = url
        result["profile"] = profile
        out(result, fmt)

    return CommandManifest(name="add", click_command=add_cmd)
