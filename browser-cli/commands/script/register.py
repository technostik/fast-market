from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.completion import ScriptPathParamType, resolve_script_path
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    launch_browser,
    out,
    read_stdin,
    run_instructions,
    stop_browser,
    substitute_params,
)


def _split_instructions(raw: str) -> list[str]:
    """Split raw script content by ';;' separator."""
    parts = raw.split(";;")
    instructions = []
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            instructions.append(cleaned)
    return instructions


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("script")
    @click.argument(
        "script_input",
        required=False,
        type=ScriptPathParamType(),
    )
    @click.option(
        "--cdp-port",
        "-c",
        "cdp_port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port.",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format.",
    )
    @click.option(
        "--param",
        "-p",
        "params",
        multiple=True,
        type=str,
        default=(),
        metavar="KEY=VALUE",
        help="Set a parameter for {key} substitution (can repeat).",
    )
    @click.option(
        "--stdin",
        "-s",
        is_flag=True,
        help="Read script from stdin instead of argument.",
    )
    @click.option(
        "--file",
        "-f",
        "script_file",
        type=ScriptPathParamType(),
        default=None,
        help="Read script from a file (searched in workdir if relative).",
    )
    @click.option(
        "--keep-browser",
        "-k",
        is_flag=True,
        help="Do not stop the browser after the script completes.",
    )
    @click.option(
        "--timeout",
        "-t",
        "timeout",
        type=int,
        default=None,
        help="Timeout in milliseconds for each agent-browser instruction.",
    )
    def script_cmd(
        script_input: str | None,
        cdp_port: int,
        fmt: str,
        params: tuple[str, ...],
        stdin: bool,
        script_file: str | None,
        keep_browser: bool,
        timeout: int | None,
    ) -> None:
        """Run agent-browser instruction(s).

        SCRIPT_INPUT is either the script content, a single instruction,
        a file path when using --file, or read from stdin with --stdin.

        Multiple instructions can be separated by ';;' on a single line,
        or by newlines in multi-line scripts.

        Use -p KEY=VALUE to set {key} placeholders in the instructions.

        If no browser is detected on CDP, one is launched and stopped after
        the script finishes (unless --keep-browser is set).
        """
        ensure_agent_browser_installed()

        param_dict: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.ClickException(
                    f"Invalid parameter format: '{p}'. Use KEY=VALUE."
                )
            key, value = p.split("=", 1)
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            param_dict[key] = value

        if script_file:
            from pathlib import Path
            resolved = resolve_script_path(script_file)
            if resolved is None:
                raise click.ClickException(f"Script file not found: {script_file}")
            script_content = resolved.read_text().strip()
        elif stdin or script_input == "-":
            script_content = read_stdin()
        elif script_input is None:
            raise click.ClickException(
                "SCRIPT_INPUT is required (or use --stdin/-s or --file/-f)."
            )
        else:
            if "\n" in script_input:
                script_content = script_input.strip()
            else:
                resolved = resolve_script_path(script_input)
                if resolved is not None:
                    script_content = resolved.read_text().strip()
                else:
                    script_content = script_input.strip()

        raw_instructions: list[str] = []
        if ";;" in script_content:
            parts = _split_instructions(script_content)
            for part in parts:
                for line in part.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "#" in line:
                        line = line.split("#", 1)[0].strip()
                    if line:
                        raw_instructions.append(line)
        else:
            for line in script_content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "#" in line:
                    line = line.split("#", 1)[0].strip()
                if line:
                    raw_instructions.append(line)

        if not raw_instructions:
            raise click.ClickException("No instructions found in script.")

        instructions = [substitute_params(inst, param_dict) for inst in raw_instructions]

        launched_browser = False
        if not is_cdp_available(cdp_port):
            launched_browser = True
            launch_browser(cdp_port)

        try:
            results, errors = run_instructions(instructions, cdp_port, timeout, fmt)
        finally:
            if launched_browser and not keep_browser:
                stop_browser(cdp_port)
                if fmt == "text":
                    click.echo("Browser stopped.", err=True)

        if fmt == "json":
            out({"instructions": len(instructions), "errors": len(errors), "results": results}, fmt)
        else:
            if errors:
                click.echo(
                    f"\n{len(errors)} error(s) in {len(instructions)} instruction(s).",
                    err=True,
                )
                raise SystemExit(1)
            else:
                click.echo(
                    f"\n{len(instructions)} instruction(s) completed successfully.",
                    err=True,
                )

    return CommandManifest(
        name="script",
        click_command=script_cmd,
    )
