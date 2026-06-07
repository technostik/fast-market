from __future__ import annotations

import sys

import click
from click.shell_completion import CompletionItem

from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    launch_hidden_browser,
    read_clipboard,
    run_instructions,
    stop_browser,
    substitute_params,
)
from common.core.paths import get_browser_cmds_dir
from core.browser_cmd import BrowserCmd, discover_browser_cmds


class _CmdNameType(click.ParamType):
    name = "CMD_NAME"

    def shell_complete(self, ctx, param, incomplete):
        try:
            cmds = discover_browser_cmds(get_browser_cmds_dir())
        except Exception:
            return []
        return [
            CompletionItem(c.name, help=c.description or "")
            for c in cmds
            if c.name.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


class _CmdParamType(click.ParamType):
    name = "KEY=VALUE"

    def shell_complete(self, ctx, param, incomplete):
        cmd_name = ctx.params.get("cmd_name", "")
        if not cmd_name:
            return []
        try:
            cmd_path = get_browser_cmds_dir() / str(cmd_name)
            cmd = BrowserCmd.from_path(cmd_path)
        except Exception:
            return []

        if not cmd or not cmd.parameters:
            return []

        already = {v.split("=")[0] for v in (ctx.params.get("params") or []) if "=" in v}

        items = []
        for p in cmd.parameters:
            name = p.get("name")
            if not name or name in already:
                continue
            key = f"{name}="
            if not key.startswith(incomplete):
                continue
            desc = p.get("description", "")
            if p.get("required", False):
                desc = f"[required] {desc}".strip()
                items.insert(0, CompletionItem(key, help=desc))
            else:
                items.append(CompletionItem(key, help=desc))
        return items

    def convert(self, value, param, ctx):
        return value


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("apply")
    @click.argument("cmd_name", type=_CmdNameType())
    @click.option("--param", "-p", "params", multiple=True, type=_CmdParamType(), metavar="KEY=VALUE",
                  help="Set a parameter for {key} substitution (can repeat).")
    @click.option("--cdp-port", type=int, default=9222, show_default=True, help="Chrome DevTools Protocol port.")
    @click.option("--keep-browser", "-k", is_flag=True, help="Do not stop the browser after the command completes.")
    @click.option("--timeout", "-t", type=int, default=None, help="Timeout per instruction in milliseconds.")
    @click.option("--no-auto-browser", is_flag=True, help="Do not auto-launch browser if none is running.")
    @click.option("--dry-run", "-n", is_flag=True, help="Show resolved instructions without executing.")
    @click.option(
        "--format", "-F", "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format.",
    )
    def apply_cmd(cmd_name, params, cdp_port, keep_browser, timeout, no_auto_browser, dry_run, fmt):
        """Apply (execute) a stored browser command by name.

        CMD_NAME is the command name stored in the browser commands directory.
        Use -p KEY=VALUE to provide values for {key} placeholders.
        """
        ensure_agent_browser_installed()

        cmds_dir = get_browser_cmds_dir()
        cmd_path = cmds_dir / cmd_name
        cmd = BrowserCmd.from_path(cmd_path)

        if cmd is None:
            click.echo(f"Error: Browser command '{cmd_name}' not found in {cmds_dir}", err=True)
            sys.exit(1)

        param_dict: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.ClickException(f"Invalid parameter format: '{p}' (expected KEY=VALUE)")
            key, value = p.split("=", 1)
            param_dict[key] = value

        for p in cmd.parameters:
            pname = p.get("name", "")
            if p.get("required", False) and pname not in param_dict:
                default = p.get("default")
                if default is not None:
                    param_dict[pname] = str(default)
                else:
                    raise click.ClickException(
                        f"Required parameter '{pname}' not provided. Use: -p {pname}=<value>"
                    )
            elif pname not in param_dict and "default" in p:
                param_dict[pname] = str(p["default"])

        instructions_raw = cmd.get_instructions()
        if not instructions_raw:
            raise click.ClickException(f"Command '{cmd_name}' has no instructions.")

        import re as _re
        import shlex as _shlex
        _PLACEHOLDER_RE = _re.compile(r"\{(\w+)\}")
        uses_clipboard = any(
            m.group(1) == "clipboard"
            for line in instructions_raw
            for m in _PLACEHOLDER_RE.finditer(line)
        )
        if uses_clipboard:
            param_dict["clipboard"] = _shlex.quote(read_clipboard())

        instructions = [substitute_params(line, param_dict) for line in instructions_raw]

        if dry_run:
            click.echo(f"Command: {cmd_name}")
            if cmd.description:
                click.echo(f"Description: {cmd.description}")
            click.echo(f"Instructions ({len(instructions)}):")
            for i, inst in enumerate(instructions, 1):
                click.echo(f"  [{i}] {inst}")
            return

        launched_browser = False
        if not is_cdp_available(cdp_port) and not no_auto_browser:
            launched_browser = True
            launch_hidden_browser(cdp_port)

        import json

        try:
            results, errors = run_instructions(instructions, cdp_port, timeout, fmt)
        finally:
            if launched_browser and not keep_browser:
                stop_browser(cdp_port)
                if fmt == "text":
                    click.echo("Browser stopped.", err=True)

        if fmt == "json":
            click.echo(json.dumps({
                "command": cmd_name,
                "instructions": len(instructions),
                "errors": len(errors),
                "results": results,
            }, indent=2))
        else:
            if errors:
                click.echo(f"\n{len(errors)} error(s) in {len(instructions)} instruction(s).", err=True)
                sys.exit(1)
            else:
                click.echo(f"\n{len(instructions)} instruction(s) completed successfully.", err=True)

    return CommandManifest(name="apply", click_command=apply_cmd)
