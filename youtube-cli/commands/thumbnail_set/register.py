from __future__ import annotations

from pathlib import Path

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("thumbnail-set")
    @click.argument("video_id")
    @click.option(
        "--file",
        "-f",
        "file",
        required=True,
        type=click.Path(exists=True),
        help="Thumbnail image file to set on the video",
    )
    def thumbnail_set_cmd(video_id: str, file: str):
        """Set the thumbnail of an already-published YouTube video."""
        from core.engine import build_youtube_client
        from googleapiclient.http import MediaFileUpload  # type: ignore[import]

        client = build_youtube_client()
        client.youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(file, resumable=True),
        ).execute()
        click.echo(f"Thumbnail updated for video {video_id}")

    return CommandManifest(name="thumbnail-set", click_command=thumbnail_set_cmd)
