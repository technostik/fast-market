from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


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
            "categoryId": "22",
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
    def upload_cmd(
        video_file: str,
        title: str,
        description: str,
        tags: str,
        privacy: str,
        thumbnail: str | None,
    ):
        """Upload a video to YouTube."""
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        click.echo(f"Uploading {Path(video_file).name}...", err=True)

        def _progress(pct: int) -> None:
            click.echo(f"Upload {pct}%...", err=True)

        url = upload_video(video_file, title, description, tags_list, privacy, thumbnail, _progress)
        click.echo(url)

    return CommandManifest(name="upload", click_command=upload_cmd)
