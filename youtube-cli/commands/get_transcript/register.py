from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.youtube.transport import RSSPlaylistTransport
from common.youtube.utils import extract_video_id


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get-transcript")
    @click.argument("url")
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option(
        "--cookies",
        type=click.Path(exists=True),
        help="Path to cookies file for authenticated requests",
    )
    def get_transcript_cmd(
        url: str,
        fmt: str,
        output: str | None,
        cookies: str | None,
    ):
        video_id = extract_video_id(url)
        if not video_id:
            raise click.ClickException(f"Invalid YouTube URL: {url}")

        transport = RSSPlaylistTransport(cookies=cookies)

        try:
            transcript = transport.get_transcript(video_id, cookies)
        except Exception as exc:
            raise click.ClickException(f"Failed to get transcript: {exc}")

        if transcript is None:
            raise click.ClickException(f"Transcript unavailable for video: {video_id}")

        details = transport.get_video_details([video_id])
        detail = details.get(video_id, {})
        snippet = detail.get("snippet", {})

        result = {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "transcript": transcript,
        }

        if output:
            content = (
                json.dumps(result, ensure_ascii=False, indent=2)
                if fmt == "json"
                else yaml.dump(result, allow_unicode=True, default_flow_style=False)
                if fmt == "yaml"
                else transcript
            )
            Path(output).write_text(content)
            click.echo(f"Saved transcript to {output}")
        else:
            if fmt == "text":
                click.echo(transcript)
            else:
                out(result, fmt)

    return CommandManifest(
        name="get-transcript",
        click_command=get_transcript_cmd,
    )
