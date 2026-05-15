from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def upload_video(
    video_file: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "unlisted",
    progress_callback=None,
) -> str:
    """Upload a video to YouTube. Returns the video URL."""
    from core.engine import build_youtube_client
    from googleapiclient.http import MediaFileUpload  # type: ignore[import]

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
    request = client.youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            progress_callback(int(status.progress() * 100))

    video_id = response["id"]
    return f"https://www.youtube.com/watch?v={video_id}"


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
    def upload_cmd(
        video_file: str,
        title: str,
        description: str,
        tags: str,
        privacy: str,
    ):
        """Upload a video to YouTube."""
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        click.echo(f"Uploading {Path(video_file).name}...", err=True)

        def _progress(pct: int) -> None:
            click.echo(f"Upload {pct}%...", err=True)

        url = upload_video(video_file, title, description, tags_list, privacy, _progress)
        click.echo(url)

    return CommandManifest(name="upload", click_command=upload_cmd)
