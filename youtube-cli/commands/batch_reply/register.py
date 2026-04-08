from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.config import load_tool_config
from common.core.yaml_utils import dump_yaml
from common.llm.base import LLMRequest
from common.llm.registry import discover_providers, get_default_provider_name


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("batch-reply")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option(
        "--prompt",
        "-p",
        required=True,
        help="Prompt template for generating replies (same for all comments)",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="json",
        help="Output format",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.pass_context
    def batch_reply_cmd(ctx, input_file, prompt, fmt, output, **kwargs):
        try:
            # Load LLM config and discover providers
            config = load_tool_config("youtube")
            providers = discover_providers(config)
            if not providers:
                click.echo("Error: No LLM providers configured. Run: common-setup", err=True)
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

            # Process comments sequentially
            results = []
            total = len(data)
            for idx, item in enumerate(data, 1):
                comment_text = item.get("text", "")
                author = item.get("author", "")
                video_url = item.get("video_url", "")

                if not comment_text:
                    continue

                # Build prompt
                user_prompt = f"{prompt}\n\n---\nComment by: {author}\nVideo: {video_url}\nComment: {comment_text}\n---\n\nGenerate a reply:"

                # Call LLM
                request = LLMRequest(
                    prompt=user_prompt,
                    temperature=0.7,
                    max_tokens=512,
                )
                response = provider.complete(request)
                reply_text = response.content.strip()

                # Build result entry with full original data
                result = {
                    "video_url": video_url,
                    "original_comment": item,
                    "reply": reply_text,
                }
                results.append(result)

                # Progress output
                click.echo(f"[{idx}/{total}] Generated reply for comment by {author}", err=True)

            # Output results
            if output:
                Path(output).write_text(
                    json.dumps(results, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else dump_yaml(results)
                )
                click.echo(f"Saved {len(results)} replies to {output}", err=True)
            else:
                out(results, fmt)

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="batch-reply",
        click_command=batch_reply_cmd,
    )
