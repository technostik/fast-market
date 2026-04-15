from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from common.youtube.transport import RSSPlaylistTransport
from common.youtube.utils import extract_video_id


def _resolve_input_path(input_file: str) -> Path:
    """Resolve input file path using common workdir."""
    from common.core.config import load_common_config

    input_path = Path(input_file)
    if not input_path.is_absolute():
        common_config = load_common_config()
        workdir = common_config.get("workdir")
        if workdir:
            workdir_path = Path(workdir).expanduser().resolve()
            return workdir_path / input_file
        return Path.cwd() / input_file
    return input_path


def _resolve_output_path(output: str) -> Path:
    """Resolve output file path using common workdir."""
    from common.core.config import load_common_config

    output_path = Path(output)
    if not output_path.is_absolute():
        common_config = load_common_config()
        workdir = common_config.get("workdir")
        if workdir:
            workdir_path = Path(workdir).expanduser().resolve()
            return workdir_path / output
        return Path.cwd() / output
    return output_path


def _detect_format_from_filename(filename: str) -> str:
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "json"


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("batch-transcript")
    @click.argument("input_file", type=str)
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml"]),
        default=None,
        help="Output format (auto-detected from file extension if not specified)",
    )
    @click.option(
        "--cookies",
        type=click.Path(exists=True),
        help="Path to cookies file for authenticated requests",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.pass_context
    def batch_transcript_cmd(
        ctx,
        input_file: str,
        fmt: str | None,
        cookies: str | None,
        output: str | None,
    ):
        input_path = _resolve_input_path(input_file)

        if not input_path.exists():
            raise click.ClickException(
                f"Error: Invalid value for 'INPUT_FILE': Path '{input_file}' does not exist."
            )

        try:
            data = json.loads(input_path.read_text())
        except json.JSONDecodeError:
            data = yaml.safe_load(input_path.read_text())

        if not isinstance(data, list):
            data = [data]

        transport = RSSPlaylistTransport(cookies=cookies)

        video_ids = [item.get("video_id") for item in data if item.get("video_id")]
        all_details = {}
        if video_ids:
            all_details = transport.get_video_details(video_ids)

        results = []
        total = len(data)
        for idx, item in enumerate(data, 1):
            video_id = item.get("video_id", "")
            error = None
            transcript = None
            transcript_raw = None

            if video_id:
                try:
                    transcript = transport.get_transcript(video_id, cookies)
                    if transcript is None:
                        error = "Transcript unavailable"
                except Exception as e:
                    error = str(e)

            detail = all_details.get(video_id, {})
            snippet = detail.get("snippet", {})

            result = {
                "channel_id": item.get("channel_id", ""),
                "channel_name": item.get("channel_name", ""),
                "video_id": video_id,
                "title": item.get("title") or snippet.get("title", ""),
                "description": item.get("description")
                or snippet.get("description", ""),
                "url": item.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                "published_at": item.get("published_at", ""),
                "transcript": transcript or "",
                "transcript_raw": transcript_raw or "",
            }
            if error:
                result["_comment"] = error

            results.append(result)

            if error:
                click.echo(f"[{idx}/{total}] Error for {video_id}: {error}", err=True)
            else:
                click.echo(f"[{idx}/{total}] Got transcript for {video_id}", err=True)

        output_path = None
        if output:
            output_path = _resolve_output_path(output)
            output_fmt = fmt if fmt else _detect_format_from_filename(output)

            if output_fmt == "json":
                output_path.write_text(
                    json.dumps(results, ensure_ascii=False, default=str)
                )
            elif output_fmt == "yaml":
                output_path.write_text(dump_yaml(results))
            click.echo(f"Saved {len(results)} transcripts to {output}", err=True)
        else:
            out(results, fmt if fmt else "json")

    return CommandManifest(
        name="batch-transcript",
        click_command=batch_transcript_cmd,
    )
