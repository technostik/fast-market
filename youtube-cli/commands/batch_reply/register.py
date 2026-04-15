from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.config import load_tool_config
from common.core.yaml_utils import dump_yaml
from common.llm.base import LLMRequest
from common.llm.registry import discover_providers, get_default_provider_name
from commands.batch_reply.prompt_processor import (
    process_prompts,
    PromptProcessorError,
)


def _detect_format_from_filename(filename: str) -> str:
    """Auto-detect output format from file extension."""
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "text"


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("batch-reply")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option(
        "--prompt",
        "-p",
        multiple=True,
        help="Prompt template for generating replies (LLM mode). Can be used multiple times. "
        "Supports @filename to include file contents, @- for stdin, "
        "and template variables like {URL}, {AUTHOR}, {COMMENT}. "
        "Use --shell for custom command mode.",
    )
    @click.option(
        "--shell",
        "-s",
        type=str,
        default=None,
        help="Shell command to generate replies. Receives comment via env vars: "
        "AUTHOR, COMMENT, VIDEO_URL, VIDEO_ID, VIDEO_TITLE, COMMENT_ID. "
        "Output should be plain text reply.",
    )
    @click.option(
        "--metadata",
        "-m",
        "metadata",
        multiple=True,
        help="Key-value pairs to include in output (repeatable). Format: key=value",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default=None,
        help="Output format (auto-detected from file extension if not specified)",
    )
    @click.option(
        "--filter",
        "filter_ids",
        type=str,
        default=None,
        help="JSON list of comment IDs to process only those comments. "
        'Example: \'["comment_id_1", "comment_id_2"]\'',
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.pass_context
    def batch_reply_cmd(
        ctx, input_file, prompt, shell, metadata, fmt, filter_ids, output, **kwargs
    ):
        # Parse metadata into dict
        metadata_dict = {}
        for m in metadata:
            if "=" in m:
                key, value = m.split("=", 1)
                metadata_dict[key] = value

        # Determine generation mode
        use_shell = bool(shell)
        use_llm = bool(prompt) and not use_shell

        if not use_shell and not use_llm:
            click.echo("Error: Either --prompt or --shell is required", err=True)
            return

        # Initialize provider if using LLM mode
        provider = None
        if use_llm:
            config = load_tool_config("youtube")
            providers = discover_providers(config)
            if not providers:
                click.echo(
                    "Error: No LLM providers configured. Run: toolsetup", err=True
                )
                return
            provider_name = get_default_provider_name(config)
            provider = providers.get(provider_name)
            if provider is None:
                click.echo(
                    f"Error: Default provider '{provider_name}' not available", err=True
                )
                return

        # Read input file
        input_path = Path(input_file)
        try:
            data = json.loads(input_path.read_text())
        except json.JSONDecodeError:
            data = yaml.safe_load(input_path.read_text())

        if not isinstance(data, list):
            data = [data]

        # Apply filter if provided
        if filter_ids:
            try:
                filter_list = json.loads(filter_ids)
                if not isinstance(filter_list, list):
                    click.echo(
                        "Error: --filter must be a JSON list of comment IDs", err=True
                    )
                    return
                filter_set = set(filter_list)
                data = [item for item in data if item.get("id") in filter_set]
                click.echo(
                    f"Filtered to {len(data)} comments matching filter IDs", err=True
                )
            except json.JSONDecodeError as e:
                click.echo(f"Error: --filter contains invalid JSON: {e}", err=True)
                return

        # Process comments sequentially
        results = []
        total = len(data)
        for idx, item in enumerate(data, 1):
            comment_text = item.get("text", "")
            author = item.get("author", "")
            video_url = item.get("video_url", "")
            video_id = item.get("video_id", "")
            video_title = item.get("video_title", "")
            comment_id = item.get("id", "")

            if not comment_text:
                continue

            reply_text = None
            error = None

            if use_shell:
                # Execute shell command with env vars
                env = {
                    **os.environ,
                    "AUTHOR": author,
                    "COMMENT": comment_text,
                    "COMMENT_TEXT": comment_text,
                    "VIDEO_URL": video_url,
                    "VIDEO_ID": video_id,
                    "VIDEO_TITLE": video_title,
                    "COMMENT_ID": comment_id,
                }
                try:
                    result = subprocess.run(
                        shell,
                        shell=True,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=30,
                    )
                    if result.returncode != 0:
                        error = (
                            result.stderr.strip() or f"Exit code: {result.returncode}"
                        )
                    else:
                        reply_text = result.stdout.strip()
                except subprocess.TimeoutExpired:
                    error = "Command timed out after 30 seconds"
                except Exception as e:
                    error = str(e)
            else:
                # Use LLM mode
                try:
                    processed_prompt = process_prompts(
                        prompts=list(prompt),
                        data=item,
                        working_dir=input_path.parent,
                    )
                except PromptProcessorError as e:
                    error = f"Error processing prompt: {e}"
                    click.echo(f"[{idx}/{total}] {error}", err=True)

                if not error:
                    user_prompt = f"{processed_prompt}\n\n---\nComment by: {author}\nVideo: {video_url}\nComment: {comment_text}\n---\n\nGenerate a reply:"
                    request = LLMRequest(
                        prompt=user_prompt,
                        temperature=0.7,
                        max_tokens=512,
                    )
                    try:
                        response = provider.complete(request)
                        reply_text = response.content.strip()
                    except Exception as e:
                        error = f"LLM error: {e}"

            # Build result entry with full original data
            result = {
                "video_url": video_url,
                "original_comment": item,
                "reply": reply_text,
            }
            if metadata_dict:
                result["metadata"] = metadata_dict
            if error:
                result["error"] = error
            results.append(result)

            if error:
                click.echo(
                    f"[{idx}/{total}] Error for comment by {author}: {error}", err=True
                )
            else:
                click.echo(
                    f"[{idx}/{total}] Generated reply for comment by {author}", err=True
                )

        # Output results
        if output:
            output_fmt = fmt if fmt else _detect_format_from_filename(output)

            if output_fmt == "json":
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, default=str)
                )
            elif output_fmt == "yaml":
                Path(output).write_text(dump_yaml(results))
            else:
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, default=str)
                )
            click.echo(f"Saved {len(results)} replies to {output}", err=True)
        else:
            out(results, fmt if fmt else "json")

    return CommandManifest(
        name="batch-reply",
        click_command=batch_reply_cmd,
    )
