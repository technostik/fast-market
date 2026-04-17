from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.config import load_tool_config, load_common_config
from common.core.yaml_utils import dump_yaml
from common.llm.base import LLMRequest
from common.llm.registry import discover_providers, get_default_provider_name
from commands.batch_reply.prompt_processor import (
    process_prompts,
    PromptProcessorError,
)
from commands.batch_utils import validate_required_fields, format_field_list


def _detect_format_from_filename(filename: str) -> str:
    """Auto-detect output format from file extension."""
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "text"


def register(plugin_manifests: dict) -> CommandManifest:
    DEFAULT_REQUIRED_FIELDS = [
        "comment_text",
        "author",
        "video_url",
        "video_id",
        "video_title",
        "comment_id",
    ]

    @click.command("batch-reply")
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
        "AUTHOR, COMMENT_TEXT, VIDEO_URL, VIDEO_ID, VIDEO_TITLE, COMMENT_ID. "
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
        help="JSON list of comment IDs to process. In rewrite mode, specifies which replies to regenerate.",
    )
    @click.option(
        "--rewrite",
        is_flag=True,
        default=False,
        help="Rewrite existing output file: regenerate filtered IDs, keep others unchanged. "
        "Requires --filter. Cannot be used with --output.",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.pass_context
    def batch_reply_cmd(
        ctx,
        input_file,
        required_fields,
        prompt,
        shell,
        metadata,
        fmt,
        filter_ids,
        rewrite,
        output,
        **kwargs,
    ):
        # Validate rewrite options
        if rewrite and not output:
            click.echo("Error: --rewrite requires --output", err=True)
            return

        if rewrite and not filter_ids:
            click.echo("Error: --rewrite requires --filter", err=True)
            return

        # Parse filter_ids
        filter_ids_set = None
        if filter_ids:
            try:
                filter_ids_list = json.loads(filter_ids)
                if not isinstance(filter_ids_list, list):
                    click.echo(
                        "Error: --filter must be a JSON list of comment IDs",
                        err=True,
                    )
                    return
                filter_ids_set = set(filter_ids_list)
            except json.JSONDecodeError as e:
                click.echo(f"Error: --filter contains invalid JSON: {e}", err=True)
                return
        # Parse metadata into dict
        metadata_dict = {}
        for m in metadata:
            if "=" in m:
                key, value = m.split("=", 1)
                metadata_dict[key] = value

        # Resolve input file path
        input_path = Path(input_file)
        if not input_path.is_absolute():
            # First, try the configured workdir
            common_config = load_common_config()
            workdir = common_config.get("workdir")
            if workdir:
                workdir_path = Path(workdir).expanduser().resolve()
                workdir_input = workdir_path / input_file
                if workdir_input.exists():
                    input_path = workdir_input
                else:
                    # Fall back to current working directory
                    input_path = Path.cwd() / input_file
            else:
                # No workdir configured, use current directory
                input_path = Path.cwd() / input_file

        if not input_path.exists():
            click.echo(
                f"Error: Invalid value for 'INPUT_FILE': Path '{input_file}' does not exist.",
                err=True,
            )
            return

        # Resolve output file path if provided
        if output:
            output_path = Path(output)
            if not output_path.is_absolute():
                # Use workdir if configured, otherwise current directory
                common_config = load_common_config()
                workdir = common_config.get("workdir")
                if workdir:
                    workdir_path = Path(workdir).expanduser().resolve()
                    output_path = workdir_path / output
                else:
                    output_path = Path.cwd() / output
            output = str(output_path)

        # Determine generation mode
        use_shell = bool(shell)
        use_llm = bool(prompt) and not use_shell
        use_shell_with_prompt = use_shell and prompt  # Shell mode with prompt variables

        if not use_shell and not prompt:
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
        validate_required_fields(data, fields_to_require, "batch-reply")

        # Handle rewrite mode
        if rewrite:
            # Input is existing results, not raw comments
            # We need to regenerate only the specified IDs
            existing_results = data
            existing_map = {
                item.get("original_comment", {}).get("comment_id"): idx
                for idx, item in enumerate(existing_results)
                if item.get("original_comment", {}).get("comment_id")
            }

            # Process only the filtered IDs
            data_to_process = []
            for comment_id in filter_ids_set:
                if comment_id in existing_map:
                    idx = existing_map[comment_id]
                    data_to_process.append(existing_results[idx]["original_comment"])
                else:
                    click.echo(
                        f"Warning: ID {comment_id} not found in input file", err=True
                    )

            if not data_to_process:
                click.echo("Error: No matching IDs found in input file", err=True)
                return

            click.echo(
                f"Rewriting {len(data_to_process)} replies in existing file", err=True
            )
            data = data_to_process
        else:
            # Apply filter if provided (only in non-rewrite mode)
            if filter_ids:
                try:
                    filter_list = json.loads(filter_ids)
                    if not isinstance(filter_list, list):
                        click.echo(
                            "Error: --filter must be a JSON list of comment IDs",
                            err=True,
                        )
                        return
                    filter_set = set(filter_list)
                    data = [
                        item for item in data if item.get("comment_id") in filter_set
                    ]
                    click.echo(
                        f"Filtered to {len(data)} comments matching filter IDs",
                        err=True,
                    )
                except json.JSONDecodeError as e:
                    click.echo(f"Error: --filter contains invalid JSON: {e}", err=True)
                    return

        # Process comments sequentially
        results = []
        total = len(data)
        for idx, item in enumerate(data, 1):
            comment_text = item.get("comment_text", "")
            author = item.get("author", "")
            video_url = item.get("video_url", "")
            video_id = item.get("video_id", "")
            video_title = item.get("video_title", "")
            comment_id = item.get("comment_id", "")

            if not comment_text:
                continue

            reply_text = None
            error = None

            if use_shell:
                # Build the actual command to execute
                actual_command = shell

                # If using shell with prompt variables, append them as command-line arguments
                if use_shell_with_prompt and prompt:
                    prompt_args = " ".join(prompt)
                    actual_command = f"{shell} {prompt_args}"

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
                        actual_command,
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

            # Build result entry with all original fields plus reply
            result = dict(item)
            result["reply"] = reply_text
            result["original_comment"] = item  # Keep for rewrite mode compatibility
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
        if rewrite:
            # Read original input file again to preserve non-regenerated entries
            try:
                original_data = json.loads(input_path.read_text())
            except json.JSONDecodeError:
                original_data = yaml.safe_load(input_path.read_text())

            if not isinstance(original_data, list):
                original_data = [original_data]

            # Build map of regenerated results by comment ID
            regenerated_map = {
                item.get("original_comment", {}).get("comment_id"): item
                for item in results
            }

            # Merge: keep original for non-regenerated, use new for regenerated
            merged = []
            for item in original_data:
                comment_id = item.get("original_comment", {}).get("comment_id")
                if comment_id in regenerated_map:
                    new_item = regenerated_map[comment_id]
                    # Preserve original metadata
                    original_metadata = item.get("metadata", {})
                    if original_metadata:
                        new_item["metadata"] = original_metadata
                    merged.append(new_item)
                else:
                    merged.append(item)

            # Write to output file
            output_path = Path(output)
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2, default=str)
            )
            click.echo(f"Updated {len(results)} replies in {output}", err=True)
            click.echo(f"Updated {len(results)} replies in {output}", err=True)
        elif output:
            output_fmt = fmt if fmt else _detect_format_from_filename(output)

            if output_fmt == "json":
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, indent=2, default=str)
                )
            elif output_fmt == "yaml":
                Path(output).write_text(dump_yaml(results))
            else:
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, indent=2, default=str)
                )
            click.echo(f"Saved {len(results)} replies to {output}", err=True)
        else:
            out(results, fmt if fmt else "json")

    return CommandManifest(
        name="batch-reply",
        click_command=batch_reply_cmd,
    )
