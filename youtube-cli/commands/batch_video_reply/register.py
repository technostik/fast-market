from __future__ import annotations

import json
import os
import re
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
from commands.batch_video_reply.prompt_processor import (
    process_prompts,
    PromptProcessorError,
)


def _detect_format_from_filename(filename: str) -> str:
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "text"


def _sanitize_key(key: str) -> str:
    sanitized = key.upper()
    sanitized = re.sub(r"[^A-Z0-9_]", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("_")


def _flatten_dict(data: dict, parent_key: str = "", sep: str = "_") -> dict:
    items = {}
    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, new_key, sep))
        elif isinstance(value, list):
            items[new_key] = json.dumps(value)
        else:
            items[new_key] = str(value) if value is not None else ""
    return items


def _item_to_env_vars(item: dict) -> dict:
    all_vars = {}
    fixed_vars = {
        "VIDEO_URL": item.get("url", ""),
        "VIDEO_ID": item.get("video_id", ""),
        "VIDEO_TITLE": item.get("title", ""),
        "VIDEO_DESCRIPTION": item.get("description", ""),
        "CHANNEL_NAME": item.get("channel_name", ""),
        "CHANNEL_ID": item.get("channel_id", ""),
        "TRANSCRIPT": item.get("transcript", ""),
        "PUBLISHED_AT": item.get("published_at", ""),
    }
    for k, v in fixed_vars.items():
        if v:
            all_vars[k] = v

    flattened = _flatten_dict(item)
    for key, value in flattened.items():
        env_key = _sanitize_key(key)
        if env_key and value:
            all_vars[env_key] = value

    return all_vars


def _resolve_input_path(input_file: str) -> Path:
    input_path = Path(input_file)
    if not input_path.is_absolute():
        common_config = load_common_config()
        workdir = common_config.get("workdir")
        if workdir:
            workdir_path = Path(workdir).expanduser().resolve()
            workdir_input = workdir_path / input_file
            if workdir_input.exists():
                return workdir_input
            return Path.cwd() / input_file
        return Path.cwd() / input_file
    return input_path


def _resolve_output_path(output: str) -> Path:
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
    @click.command("batch-video-reply")
    @click.argument("input_file", type=str)
    @click.option(
        "--prompt",
        "-p",
        multiple=True,
        help="Prompt template for generating replies (LLM mode). Can be used multiple times. "
        "Supports @filename to include file contents, @- for stdin, "
        "and template variables like {VIDEO_TITLE}, {VIDEO_DESCRIPTION}, {TRANSCRIPT}. "
        "Use --shell for custom command mode.",
    )
    @click.option(
        "--shell",
        "-s",
        type=str,
        default=None,
        help="Shell command to generate replies. Receives video data via env vars: "
        "VIDEO_URL, VIDEO_ID, VIDEO_TITLE, VIDEO_DESCRIPTION, CHANNEL_NAME, CHANNEL_ID, TRANSCRIPT. "
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
        help="JSON list of video IDs to process. In rewrite mode, specifies which replies to regenerate.",
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
    def batch_video_reply_cmd(
        ctx,
        input_file,
        prompt,
        shell,
        metadata,
        fmt,
        filter_ids,
        rewrite,
        output,
        **kwargs,
    ):
        if rewrite and not output:
            click.echo("Error: --rewrite requires --output", err=True)
            return

        if rewrite and not filter_ids:
            click.echo("Error: --rewrite requires --filter", err=True)
            return

        filter_ids_set = None
        if filter_ids:
            try:
                filter_ids_list = json.loads(filter_ids)
                if not isinstance(filter_ids_list, list):
                    click.echo(
                        "Error: --filter must be a JSON list of video IDs",
                        err=True,
                    )
                    return
                filter_ids_set = set(filter_ids_list)
            except json.JSONDecodeError as e:
                click.echo(f"Error: --filter contains invalid JSON: {e}", err=True)
                return

        metadata_dict = {}
        for m in metadata:
            if "=" in m:
                key, value = m.split("=", 1)
                metadata_dict[key] = value

        input_path = _resolve_input_path(input_file)

        if not input_path.exists():
            click.echo(
                f"Error: Invalid value for 'INPUT_FILE': Path '{input_file}' does not exist.",
                err=True,
            )
            return

        if output:
            output_path = _resolve_output_path(output)
            output = str(output_path)

        use_shell = bool(shell)
        use_llm = bool(prompt) and not use_shell
        use_shell_with_prompt = use_shell and prompt

        if not use_shell and not prompt:
            click.echo("Error: Either --prompt or --shell is required", err=True)
            return

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

        try:
            data = json.loads(input_path.read_text())
        except json.JSONDecodeError:
            data = yaml.safe_load(input_path.read_text())

        if not isinstance(data, list):
            data = [data]

        if rewrite:
            existing_results = data
            existing_map = {
                item.get("video_id"): idx
                for idx, item in enumerate(existing_results)
                if item.get("video_id")
            }

            data_to_process = []
            for video_id in filter_ids_set:
                if video_id in existing_map:
                    idx = existing_map[video_id]
                    data_to_process.append(existing_results[idx])
                else:
                    click.echo(
                        f"Warning: Video ID {video_id} not found in input file",
                        err=True,
                    )

            if not data_to_process:
                click.echo("Error: No matching IDs found in input file", err=True)
                return

            click.echo(
                f"Rewriting {len(data_to_process)} replies in existing file", err=True
            )
            data = data_to_process
        else:
            if filter_ids:
                try:
                    filter_list = json.loads(filter_ids)
                    if not isinstance(filter_list, list):
                        click.echo(
                            "Error: --filter must be a JSON list of video IDs",
                            err=True,
                        )
                        return
                    filter_set = set(filter_list)
                    data = [item for item in data if item.get("video_id") in filter_set]
                    click.echo(
                        f"Filtered to {len(data)} videos matching filter IDs",
                        err=True,
                    )
                except json.JSONDecodeError as e:
                    click.echo(f"Error: --filter contains invalid JSON: {e}", err=True)
                    return

        results = []
        total = len(data)
        for idx, item in enumerate(data, 1):
            video_id = item.get("video_id", "")
            video_url = item.get("url", "")
            video_title = item.get("title", "")
            description = item.get("description", "")
            channel_name = item.get("channel_name", "")
            channel_id = item.get("channel_id", "")
            transcript = item.get("transcript", "")
            published_at = item.get("published_at", "")

            if not video_id:
                continue

            reply_text = None
            error = None

            if use_shell:
                actual_command = shell

                if use_shell_with_prompt and prompt:
                    prompt_args = " ".join(prompt)
                    actual_command = f"{shell} {prompt_args}"

                env = {
                    **os.environ,
                    **_item_to_env_vars(item),
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
                    user_prompt = f"{processed_prompt}\n\n---\nVideo title: {video_title}\nChannel: {channel_name}\nDescription: {description}\nTranscript:\n{transcript}\n---\n\nGenerate a reply:"
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

            result = {
                "channel_id": channel_id,
                "channel_name": channel_name,
                "video_id": video_id,
                "title": video_title,
                "description": description,
                "url": video_url,
                "published_at": published_at,
                "transcript": transcript,
                "reply": reply_text,
            }
            if metadata_dict:
                result["metadata"] = metadata_dict
            if error:
                result["error"] = error
            results.append(result)

            if error:
                click.echo(
                    f"[{idx}/{total}] Error for video {video_id}: {error}", err=True
                )
            else:
                click.echo(
                    f"[{idx}/{total}] Generated reply for video {video_id}", err=True
                )

        if rewrite:
            try:
                original_data = json.loads(input_path.read_text())
            except json.JSONDecodeError:
                original_data = yaml.safe_load(input_path.read_text())

            if not isinstance(original_data, list):
                original_data = [original_data]

            regenerated_map = {item.get("video_id"): item for item in results}

            merged = []
            for item in original_data:
                video_id = item.get("video_id")
                if video_id in regenerated_map:
                    new_item = regenerated_map[video_id]
                    original_metadata = item.get("metadata", {})
                    if original_metadata:
                        new_item["metadata"] = original_metadata
                    merged.append(new_item)
                else:
                    merged.append(item)

            output_path = Path(output)
            output_path.write_text(json.dumps(merged, ensure_ascii=False, default=str))
            click.echo(f"Updated {len(results)} replies in {output}", err=True)
        elif output:
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
        name="batch-video-reply",
        click_command=batch_video_reply_cmd,
    )
