from __future__ import annotations

import tempfile
from pathlib import Path

import click
from PIL import Image

from commands.base import CommandManifest

# YouTube thumbnail requirements.
YT_W, YT_H = 1280, 720
YT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB hard limit enforced by the API


def _prepare_thumbnail(file: str) -> tuple[str, bool]:
    """Return ``(path, was_resized)`` for an upload-ready thumbnail.

    - Warns (to stderr) when the source is not exactly 1280x720.
    - Resizes/pads to 1280x720 (keep aspect, letterbox on black) so the
      proportion is correct.
    - Re-encodes to keep the file under the 2 MiB limit.
    The prepared file is written to a temp path and returned for upload."""
    src = Path(file).expanduser().resolve()
    img = Image.open(src).convert("RGB")
    was_resized = False

    if img.size != (YT_W, YT_H):
        click.echo(
            f"Warning: thumbnail is {img.size[0]}x{img.size[1]}, YouTube expects "
            f"{YT_W}x{YT_H} (16:9). Resizing/padding to fit.",
            err=True,
        )
        was_resized = True
        # Scale to fit inside the 1280x720 box, preserving aspect ratio.
        img.thumbnail((YT_W, YT_H), Image.LANCZOS)
        canvas = Image.new("RGB", (YT_W, YT_H), (0, 0, 0))
        canvas.paste(img, ((YT_W - img.width) // 2, (YT_H - img.height) // 2))
        img = canvas

    # Encode to a temp file, downscaling quality until under the size limit.
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="yt-thumb-")
    tmp_path = tmp.name
    tmp.close()

    quality = 95
    while True:
        img.save(tmp_path, format="JPEG", quality=quality, optimize=True)
        size = Path(tmp_path).stat().st_size
        if size <= YT_MAX_BYTES or quality <= 20:
            break
        quality -= 10

    if Path(tmp_path).stat().st_size > YT_MAX_BYTES:
        click.echo(
            f"Warning: prepared thumbnail is still {Path(tmp_path).stat().st_size} bytes "
            f"(> 2 MiB limit); upload may fail.",
            err=True,
        )

    return tmp_path, was_resized


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
        """Set the thumbnail of an already-published YouTube video.

        The image is auto-prepared for YouTube: if it is not exactly 1280x720 it
        is resized/padded to the correct 16:9 proportion, and it is re-encoded to
        stay under the 2 MiB upload limit. A warning is printed to stderr when
        any adjustment was needed."""
        from core.engine import build_youtube_client
        from googleapiclient.http import MediaFileUpload  # type: ignore[import]

        prepared, was_resized = _prepare_thumbnail(file)
        client = build_youtube_client()
        client.youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(prepared, resumable=True),
        ).execute()
        if was_resized:
            click.echo("(thumbnail was resized to meet YouTube requirements)", err=True)
        click.echo(f"Thumbnail updated for video {video_id}")

    return CommandManifest(name="thumbnail-set", click_command=thumbnail_set_cmd)
