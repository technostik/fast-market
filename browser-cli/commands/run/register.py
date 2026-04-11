from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    substitute_params,
    run_agent_cmd,
    out,
    read_stdin,
)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.argument("instruction", required=False)
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
        help="Read instruction from stdin instead of argument.",
    )
    def run_cmd(
        instruction: str | None,
        cdp_port: int,
        fmt: str,
        params: tuple[str, ...],
        stdin: bool,
    ) -> None:
        """Run a single agent-browser instruction.

        INSTRUCTION is the command to run (e.g., 'open https://example.com').
        Use -p KEY=VALUE to set {key} placeholders in the instruction.
        """
        ensure_agent_browser_installed()

        # Resolve instruction from arg or stdin
        if stdin or instruction == "-":
            instruction = read_stdin()
        elif instruction is None:
            raise click.ClickException("INSTRUCTION argument is required (or use --stdin/-s).")

        # Parse parameters
        param_dict: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.ClickException(f"Invalid parameter format: '{p}'. Use KEY=VALUE.")
            key, value = p.split("=", 1)
            param_dict[key] = value

        # Substitute placeholders
        instruction = substitute_params(instruction, param_dict)

        # Run the command
        result = run_agent_cmd(instruction, cdp_port)

        if fmt == "json":
            out({
                "instruction": instruction,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.returncode,
                "success": result.returncode == 0,
            }, fmt)
        else:
            if result.stdout.strip():
                click.echo(result.stdout.strip())
            if result.returncode != 0:
                if result.stderr.strip():
                    click.echo(result.stderr.strip(), err=True)
                raise SystemExit(result.returncode)

    return CommandManifest(
        name="run",
        click_command=run_cmd,
    )
