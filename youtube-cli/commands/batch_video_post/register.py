from __future__ import annotations

import json
import time
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from core.config import load_config
from core.engine import build_youtube_client
from commands.batch_utils import validate_required_fields, format_field_list


def _resolve_input_path(input_file: str) -> Path:
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


def register(plugin_manifests: dict) -> CommandManifest:
    DEFAULT_REQUIRED_FIELDS = ["reply", "video_id", "url", "title"]

    @click.command("batch-video-post")
    @click.argument("input_file", type=str)
    @click.option(
        "--require-field",
        "-r",
        "required_fields",
        multiple=True,
        help=f"Required JSON fields (default: {format_field_list(DEFAULT_REQUIRED_FIELDS)}). "
        f"Use multiple times to require multiple fields.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Preview what would be posted without actually posting",
    )
    @click.option(
        "--delay",
        "-d",
        type=int,
        default=0,
        help="Seconds to wait between each post (default: 0)",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="json",
        help="Output format",
    )
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        help="Update input file in-place with reply status added to each video",
    )
    @click.pass_context
    def batch_video_post_cmd(
        ctx, input_file, required_fields, dry_run, delay, fmt, output, **kwargs
    ):
        try:
            config = load_config()
            client = build_youtube_client(config)

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

            # Validate required fields
            fields_to_require = (
                list(required_fields) if required_fields else DEFAULT_REQUIRED_FIELDS
            )
            validate_required_fields(data, fields_to_require, "batch-video-post")

            results = []
            errors = []
            total = len(data)

            if dry_run:
                click.echo(
                    "[DRY RUN] The following comments would be posted:\n", err=True
                )

            for idx, item in enumerate(data, 1):
                reply_text = item.get("reply", "")
                video_id = item.get("video_id", "")
                video_url = item.get("url", "")
                video_title = item.get("title", "")

                if not reply_text or not video_id:
                    err_msg = f"[{idx}/{total}] Missing reply text or video ID"
                    errors.append({"index": idx, "error": err_msg})
                    click.echo(f"  SKIP: {err_msg}", err=True)
                    continue

                # Build entry preserving all original fields
                entry = dict(item)
                entry["post_status"] = None
                entry["comment_id"] = None
                entry["moderation_status"] = None
                if "error" in entry:
                    del entry["error"]
                entry["error"] = None

                if dry_run:
                    entry["post_status"] = "dry_run"
                    click.echo(f"  [{idx}/{total}] Comment on {video_url}", err=True)
                    click.echo(f"    Text: {reply_text[:100]}...", err=True)
                else:
                    try:
                        result = client.post_comment(video_id, reply_text)
                        if result:
                            entry["post_status"] = "success"
                            entry["comment_id"] = result.id
                            entry["moderation_status"] = result.moderation_status
                            click.echo(
                                f"  [{idx}/{total}] ✓ Posted comment on {video_title} (ID: {result.id})",
                                err=True,
                            )
                        else:
                            entry["post_status"] = "failed"
                            entry["error"] = "API returned no result"
                            errors.append(
                                {
                                    "index": idx,
                                    "video_id": video_id,
                                    "error": "API returned no result",
                                }
                            )
                            click.echo(
                                f"  [{idx}/{total}] ✗ Failed: API returned no result",
                                err=True,
                            )
                    except Exception as e:
                        entry["post_status"] = "error"
                        entry["error"] = str(e)
                        errors.append(
                            {"index": idx, "video_id": video_id, "error": str(e)}
                        )
                        click.echo(
                            f"  [{idx}/{total}] ✗ Error: {e}",
                            err=True,
                        )

                results.append(entry)

                if delay > 0 and idx < total:
                    time.sleep(delay)

            success_count = sum(1 for r in results if r["post_status"] == "success")
            failed_count = sum(
                1 for r in results if r["post_status"] in ("failed", "error")
            )
            dry_count = sum(1 for r in results if r["post_status"] == "dry_run")

            click.echo(f"\n--- Summary ---", err=True)
            if dry_run:
                click.echo(f"  Would post: {dry_count} comments", err=True)
            else:
                click.echo(f"  Posted: {success_count}/{total}", err=True)
                if failed_count:
                    click.echo(f"  Failed: {failed_count}/{total}", err=True)

            if errors:
                click.echo(f"\n--- Error Report ({len(errors)} errors) ---", err=True)
                for err in errors:
                    click.echo(
                        f"  [{err['index']}] {err.get('video_id', 'N/A')}: {err['error']}",
                        err=True,
                    )

            if output:
                output_path = _resolve_output_path(output)
                output_path.write_text(
                    json.dumps(results, ensure_ascii=False, indent=2, default=str)
                    if fmt == "json"
                    else dump_yaml(results)
                )
                click.echo(f"\nSaved {len(results)} results to {output}", err=True)
            else:
                out(results, fmt)

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="batch-video-post",
        click_command=batch_video_post_cmd,
    )
