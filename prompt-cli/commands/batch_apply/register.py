from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from common import structlog

from commands.base import CommandManifest
from commands.completion import PromptNameParamType
from common.cli.helpers import out as cli_out


logger = structlog.get_logger(__name__)


def _load_file(path: Path) -> list:
    """Load JSON or YAML file based on extension."""
    content = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(content)
    else:
        data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError(
            f"Input file must contain a JSON array, got {type(data).__name__}"
        )
    return data


def _save_file(path: Path | None, data: list) -> None:
    """Save JSON or YAML file based on extension. If path is None, output to stdout."""
    if path is None:
        cli_out(data, "json")
        return

    content: str
    if path.suffix in (".yaml", ".yml"):
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    else:
        content = json.dumps(data, indent=2, ensure_ascii=False)

    path.write_text(content, encoding="utf-8")


def _resolve_prompt(prompt_name_or_content: str, prompt_store) -> tuple[str, bool]:
    """Resolve prompt: (content, is_saved)."""
    saved = prompt_store.get_prompt(prompt_name_or_content)
    if saved:
        return saved.content, True
    return prompt_name_or_content, False


def register(plugin_manifests: dict) -> CommandManifest:
    provider_choices = list(plugin_manifests.keys()) if plugin_manifests else []

    @click.command("batch-apply")
    @click.option(
        "--prompt",
        "-p",
        "prompt_content",
        default=None,
        help="Prompt template string (e.g., 'Translate: {text}')",
    )
    @click.option(
        "--prompt-name",
        "-n",
        "prompt_name",
        default=None,
        type=PromptNameParamType(),
        help="Name of a saved prompt to use",
    )
    @click.option(
        "--prompt-param",
        "-A",
        "prompt_params",
        multiple=True,
        help="Parameter for saved prompt (key=value, can repeat)",
    )
    @click.option(
        "--input-field",
        "-i",
        required=True,
        help="Field name in each record to use as input",
    )
    @click.option(
        "--output-field",
        "-o",
        required=True,
        help="Field name to store the LLM output",
    )
    @click.option(
        "--input",
        "-f",
        "input_file",
        type=click.Path(path_type=Path),
        default=None,
        help="Input JSON/YAML file (default: stdin)",
    )
    @click.option(
        "--output",
        "-O",
        "output_file",
        type=click.Path(path_type=Path),
        default=None,
        help="Output JSON/YAML file (default: stdout)",
    )
    @click.option(
        "--provider",
        "-P",
        type=click.Choice(provider_choices) if provider_choices else str,
        default=None,
    )
    @click.option("--model", "-m", default=None)
    @click.option("--temperature", "-T", type=float, default=None)
    @click.option("--max-tokens", "-M", type=int, default=None)
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show what would be processed without making LLM calls",
    )
    @click.option(
        "--limit",
        "-L",
        type=int,
        default=None,
        help="Limit number of records to process",
    )
    @click.option(
        "--workdir",
        "-w",
        type=click.Path(),
        default=None,
        help="Working directory for file paths (default: current directory or common config)",
    )
    @click.option(
        "--metadata",
        "-m",
        "metadata",
        multiple=True,
        help="Key-value pairs to include in output (repeatable). Format: key=value",
    )
    @click.pass_context
    def batch_apply_cmd(
        ctx,
        prompt_content,
        prompt_name,
        prompt_params,
        input_field,
        output_field,
        input_file,
        output_file,
        provider,
        model,
        temperature,
        max_tokens,
        dry_run,
        limit,
        workdir,
        metadata,
    ):
        """Apply a prompt to each record in a JSON array.

        Reads records from a JSON/YAML file (or stdin), applies an LLM prompt
        to the specified input field of each record, and writes the results
        to an output file (or stdout).

        \b
        Examples:
          prompt batch-apply -p "Translate: {text}" -i text -o translated -f data.json -O out.json
          prompt batch-apply -n summarize -A max_length=50 -i description -o summary -f items.yaml
          cat data.json | prompt batch-apply -p "Summarize: {desc}" -i desc -o summary
        """
        from common.core.config import load_common_config, load_tool_config
        from commands.helpers import build_engine, get_default_provider
        from core.substitution import resolve_arguments, extract_placeholders
        from storage.store import PromptStore

        if not prompt_content and not prompt_name:
            click.echo("Error: either --prompt or --prompt-name is required", err=True)
            sys.exit(1)

        if prompt_content and prompt_name:
            click.echo("Error: cannot use both --prompt and --prompt-name", err=True)
            sys.exit(1)

        if workdir:
            workdir_path = Path(workdir)
        else:
            common_config = load_common_config()
            configured_workdir = common_config.get("workdir")
            if configured_workdir:
                workdir_path = Path(configured_workdir)
            else:
                workdir_path = Path.cwd()

        input_path = input_file

        if input_path is None and sys.stdin.isatty():
            click.echo("Error: --input required or provide input via stdin", err=True)
            sys.exit(1)

        try:
            if input_path:
                if not input_path.is_absolute():
                    input_path = workdir_path / input_path
                if not input_path.exists():
                    click.echo(f"Error: input file not found: {input_path}", err=True)
                    sys.exit(1)
                records = _load_file(input_path)
            else:
                if not sys.stdin.isatty():
                    content = sys.stdin.read().strip()
                    if not content:
                        click.echo("Error: empty stdin input", err=True)
                        sys.exit(1)
                    if content.startswith(("[{", "[")):
                        records = json.loads(content)
                    else:
                        records = yaml.safe_load(content)
                    if not isinstance(records, list):
                        raise ValueError(f"Input must be a JSON array")
                else:
                    click.echo("Error: no input provided", err=True)
                    sys.exit(1)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            click.echo(f"Error: invalid input: {exc}", err=True)
            sys.exit(1)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        if limit:
            records = records[:limit]

        prompt_store = PromptStore()
        model_name = model
        temp = temperature
        max_tok = max_tokens
        resolved_prompt = None

        if prompt_name:
            resolved_prompt, is_saved = _resolve_prompt(prompt_name, prompt_store)
            placeholders = extract_placeholders(resolved_prompt)

            param_dict = {}
            for p in prompt_params:
                if "=" not in p:
                    click.echo(f"Invalid --prompt-param: {p}", err=True)
                    sys.exit(1)
                k, v = p.split("=", 1)
                param_dict[k] = v

            if input_field not in placeholders:
                if len(placeholders) == 1:
                    param_dict[placeholders[0]] = "{" + input_field + "}"
                else:
                    click.echo(
                        f"Error: prompt '{prompt_name}' has no {{{input_field}}}. "
                        f"Available: {', '.join(placeholders)}",
                        err=True,
                    )
                    sys.exit(1)

            provider_name = provider or get_default_provider()
        else:
            provider_name = provider or get_default_provider()
            placeholder_str = "{" + input_field + "}"
            if placeholder_str not in prompt_content:
                click.echo(f"Error: prompt has no {{{input_field}}}", err=True)
                sys.exit(1)

        providers = build_engine(ctx.obj["verbose"])

        if provider_name not in providers:
            click.echo(f"Provider not found: {provider_name}", err=True)
            sys.exit(1)

        metadata_dict = {}
        for m in metadata:
            if "=" in m:
                key, value = m.split("=", 1)
                metadata_dict[key] = value

        if dry_run:
            click.echo(f"Would process {len(records)} records:")
            for idx, rec in enumerate(records[:5]):
                val = rec.get(input_field, "<missing>")
                preview = str(val)[:50] + "..." if len(str(val)) > 50 else str(val)
                click.echo(f"  [{idx}] {input_field}: {preview}")
            if len(records) > 5:
                click.echo(f"  ... and {len(records) - 5} more")
            return

        from common.llm.base import LLMRequest

        results = []
        for idx, record in enumerate(records):
            input_value = record.get(input_field)
            if input_value is None:
                logger.warning("missing_input_field", index=idx, field=input_field)
                record[output_field] = None
                results.append(record)
                continue

            if prompt_name:
                resolved = resolve_arguments(resolved_prompt, param_dict, Path.cwd())
            else:
                resolved = prompt_content.replace(
                    "{" + input_field + "}", str(input_value)
                )

            request = LLMRequest(
                prompt=resolved,
                model=model_name,
                temperature=temp,
                max_tokens=max_tok,
            )

            try:
                response = providers[provider_name].complete(request)
            except Exception as exc:
                click.echo(f"Error at record {idx}: {exc}", err=True)
                record[output_field] = None
                results.append(record)
                continue

            record[output_field] = response.content
            if metadata_dict:
                record["metadata"] = metadata_dict
            results.append(record)

            if (idx + 1) % 10 == 0:
                click.echo(f"Processed {idx + 1}/{len(records)}", err=True)

        output_path = output_file
        if output_path and not output_path.is_absolute():
            output_path = workdir_path / output_path

        _save_file(output_path, results)
        click.echo(f"Done. Processed {len(results)} records.", err=True)

    return CommandManifest(name="batch-apply", click_command=batch_apply_cmd)
