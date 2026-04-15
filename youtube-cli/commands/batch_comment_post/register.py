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


def _resolve_path(file_path: str) -> Path:
    """Resolve relative file path to workdir."""
    from common.core.config import load_common_config

    path = Path(file_path)
    if not path.is_absolute():
        common_config = load_common_config()
        workdir = common_config.get("workdir")
        if workdir:
            workdir_path = Path(workdir).expanduser().resolve()
            return workdir_path / file_path
        return Path.cwd() / file_path
    return path


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("batch-comment-post")
    @click.argument("input_file", type=str)
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
        help="Update input file in-place with reply status added to each comment",
    )
    @click.pass_context
    def batch_post_cmd(ctx, input_file, dry_run, delay, fmt, output, **kwargs):
        try:
            config = load_config()
            client = build_youtube_client(config)

            # Resolve input file path
            input_path = _resolve_path(input_file)

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

            # Process replies sequentially
            results = []
            errors = []
            total = len(data)

            if dry_run:
                click.echo(
                    "[DRY RUN] The following replies would be posted:\n", err=True
                )

            for idx, item in enumerate(data, 1):
                reply_text = item.get("reply", "")
                original_comment = item.get("original_comment", {})
                video_url = item.get("video_url", "")
                comment_id = original_comment.get("id", "")
                author = original_comment.get("author", "")

                if not reply_text or not comment_id:
                    err_msg = f"[{idx}/{total}] Missing reply text or comment ID"
                    errors.append({"index": idx, "error": err_msg})
                    click.echo(f"  SKIP: {err_msg}", err=True)
                    continue

                # Build status entry
                entry = {
                    "video_url": video_url,
                    "original_comment": original_comment,
                    "reply": reply_text,
                    "post_status": None,
                    "reply_id": None,
                    "error": None,
                }

                if dry_run:
                    entry["post_status"] = "dry_run"
                    click.echo(
                        f"  [{idx}/{total}] Reply to @{author} on {video_url}", err=True
                    )
                    click.echo(f"    Text: {reply_text[:100]}...", err=True)
                else:
                    try:
                        result = client.post_comment_reply(comment_id, reply_text)
                        if result:
                            entry["post_status"] = "success"
                            entry["reply_id"] = result.id
                            entry["moderation_status"] = result.moderation_status
                            click.echo(
                                f"  [{idx}/{total}] ✓ Posted reply to @{author} (ID: {result.id})",
                                err=True,
                            )
                        else:
                            entry["post_status"] = "failed"
                            entry["error"] = "API returned no result"
                            errors.append(
                                {
                                    "index": idx,
                                    "comment_id": comment_id,
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
                            {"index": idx, "comment_id": comment_id, "error": str(e)}
                        )
                        click.echo(
                            f"  [{idx}/{total}] ✗ Error: {e}",
                            err=True,
                        )

                results.append(entry)

                # Rate limiting delay
                if delay > 0 and idx < total:
                    time.sleep(delay)

            # Summary
            success_count = sum(1 for r in results if r["post_status"] == "success")
            failed_count = sum(
                1 for r in results if r["post_status"] in ("failed", "error")
            )
            dry_count = sum(1 for r in results if r["post_status"] == "dry_run")

            click.echo(f"\n--- Summary ---", err=True)
            if dry_run:
                click.echo(f"  Would post: {dry_count} replies", err=True)
            else:
                click.echo(f"  Posted: {success_count}/{total}", err=True)
                if failed_count:
                    click.echo(f"  Failed: {failed_count}/{total}", err=True)

            if errors:
                click.echo(f"\n--- Error Report ({len(errors)} errors) ---", err=True)
                for err in errors:
                    click.echo(
                        f"  [{err['index']}] {err.get('comment_id', 'N/A')}: {err['error']}",
                        err=True,
                    )

            # Output results
            if output:
                # Update the original data with post status
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, default=str)
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
        name="batch-comment-post",
        click_command=batch_post_cmd,
    )
