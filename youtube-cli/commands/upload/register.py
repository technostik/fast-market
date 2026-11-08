from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import click

from commands.base import CommandManifest


# YouTube uses the same numeric category IDs in every region for the standard
# set. A profile stores a human-readable label (French or English), so accept
# either a label or a raw ID and resolve it to the numeric ID here.
DEFAULT_CATEGORY_ID = "22"  # People & Blogs

_CATEGORY_ALIASES: dict[str, list[str]] = {
    "1": ["film & animation", "film et animation", "films et animations"],
    "2": ["autos & vehicles", "autos et vehicules", "voitures et vehicules"],
    "10": ["music", "musique"],
    "15": ["pets & animals", "animaux", "animaux domestiques"],
    "17": ["sports", "sport"],
    "19": ["travel & events", "voyages et evenements"],
    "20": ["gaming", "jeux video"],
    "22": ["people & blogs", "personnes et blogs"],
    "23": ["comedy", "humour"],
    "24": ["entertainment", "divertissement"],
    "25": ["news & politics", "actualites et politique"],
    "26": ["howto & style", "comment faire et style"],
    "27": ["education"],
    "28": ["science & technology", "science et technologie"],
    "29": ["nonprofits & activism", "associations et militantisme"],
    "43": ["shows", "emissions"],
}


def _normalize_category(value: str) -> str:
    """Lowercase, strip accents and punctuation so labels match loosely."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " et ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


_CATEGORY_LOOKUP: dict[str, str] = {
    _normalize_category(alias): cat_id
    for cat_id, aliases in _CATEGORY_ALIASES.items()
    for alias in aliases
}


def resolve_category_id(value: str | None) -> str:
    """Resolve a category name (French/English) or numeric ID to a YouTube ID.

    Empty input falls back to the built-in default (People & Blogs).
    """
    text = (value or "").strip()
    if not text:
        return DEFAULT_CATEGORY_ID
    if text.isdigit():
        return text
    resolved = _CATEGORY_LOOKUP.get(_normalize_category(text))
    if resolved is None:
        known = ", ".join(sorted(_CATEGORY_ALIASES))
        raise click.ClickException(
            f"Unknown YouTube category {value!r}. Use a numeric ID or a known "
            f"name (IDs: {known})."
        )
    return resolved


def _format_upload_error(status: int, reason: str, body: str) -> str:
    msg = f"YouTube API returned {status} {reason}"
    if body:
        msg += f"\n{body}"
    if status == 403:
        msg += (
            "\n\nPossible causes:"
            "\n  - Quota exceeded (run 'youtube setup status' to check)"
            "\n  - OAuth token lacks upload permission (run 'youtube setup refresh')"
            "\n  - Video may violate YouTube's content policy"
        )
    elif status == 404:
        msg += "\n\nThe video file was not found or the upload session expired."
    elif status == 410:
        msg += "\n\nThe upload session expired. Try uploading again."
    elif status == 429:
        msg += "\n\nToo many requests. Wait a moment and try again."
    elif status >= 500:
        msg += "\n\nYouTube server error. Try again later."
    return msg


def upload_video(
    video_file: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "unlisted",
    thumbnail: str | None = None,
    progress_callback=None,
    category: str = "",
) -> str:
    """Upload a video to YouTube. Returns the video URL."""
    from core.engine import build_youtube_client
    from googleapiclient.http import MediaFileUpload  # type: ignore[import]
    from googleapiclient.errors import ResumableUploadError, HttpError

    client = build_youtube_client()
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": resolve_category_id(category),
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(video_file, resumable=True)
    try:
        request = client.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
    except HttpError as e:
        raise click.ClickException(
            _format_upload_error(e.resp.status, e.reason, e.content.decode(errors="replace"))
        )

    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
        except ResumableUploadError as e:
            status_code = e.resp.status if hasattr(e, "resp") else 0
            reason = e.reason if hasattr(e, "reason") else "unknown"
            body = e.content.decode(errors="replace") if hasattr(e, "content") else ""
            raise click.ClickException(_format_upload_error(status_code, reason, body))
        if status and progress_callback:
            progress_callback(int(status.progress() * 100))

    video_id = response["id"]
    watch_url = f"https://www.youtube.com/watch?v={video_id}"

    if thumbnail:
        try:
            client.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail, resumable=True),
            ).execute()
        except Exception as e:  # thumbnail failure is non-fatal
            click.echo(f"Warning: thumbnail upload failed: {e}", err=True)

    return watch_url


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("upload")
    @click.argument("video_file", type=click.Path(exists=True))
    @click.option("--title", "-t", required=True, help="Video title")
    @click.option("--description", "-d", default="", help="Video description")
    @click.option("--tags", default="", help="Comma-separated tags")
    @click.option(
        "--privacy",
        type=click.Choice(["private", "unlisted", "public"]),
        default="unlisted",
        show_default=True,
    )
    @click.option(
        "--thumbnail",
        type=click.Path(exists=True),
        default=None,
        help="Thumbnail image to set on the uploaded video",
    )
    @click.option(
        "--category",
        "-c",
        default="",
        help=(
            "YouTube category: a numeric ID or a name (e.g. 'Science et "
            "technologie'). Defaults to People & Blogs (22)."
        ),
    )
    def upload_cmd(
        video_file: str,
        title: str,
        description: str,
        tags: str,
        privacy: str,
        thumbnail: str | None,
        category: str,
    ):
        """Upload a video to YouTube."""
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        category_id = resolve_category_id(category)

        click.echo(
            f"Uploading {Path(video_file).name} (category {category_id})...", err=True
        )

        def _progress(pct: int) -> None:
            click.echo(f"Upload {pct}%...", err=True)

        url = upload_video(
            video_file, title, description, tags_list, privacy, thumbnail,
            _progress, category,
        )
        click.echo(url)

    return CommandManifest(name="upload", click_command=upload_cmd)
