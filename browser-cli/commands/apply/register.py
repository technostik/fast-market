from __future__ import annotations

import sys
import time

import click
from click.shell_completion import CompletionItem

from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    read_clipboard,
    run_agent_cmd,
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


def _launch_browser(cdp_port: int) -> None:
    import subprocess
    from pathlib import Path

    user_data_dir = str(Path.home() / ".chrome-debug-profile")
    subprocess.Popen(
        [
            "google-chrome",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--disable-features=OptimizationHints",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    click.echo(f"Launching browser on CDP port {cdp_port}...", err=True)
    for _ in range(30):
        if is_cdp_available(cdp_port):
            return
        time.sleep(0.5)
    click.echo(f"Warning: Browser may not have started on port {cdp_port}.", err=True)


def _stop_browser(cdp_port: int) -> None:
    import os
    import signal
    import subprocess

    pids: list[int] = []
    try:
        r = subprocess.run(["lsof", "-ti", f"TCP:*:{cdp_port}"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            pids = [int(p) for p in r.stdout.strip().split("\n")]
    except (FileNotFoundError, ValueError):
        pass

    if not pids:
        try:
            r = subprocess.run(
                ["pgrep", "-f", f"--remote-debugging-port={cdp_port}"],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                pids = [int(p) for p in r.stdout.strip().split("\n")]
        except (FileNotFoundError, ValueError):
            pass

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    time.sleep(0.5)

    for pid in pids:
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("apply")
    @click.argument("cmd_name", type=_CmdNameType())
    @click.argument("params", nargs=-1, type=_CmdParamType())
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
        PARAMS are KEY=VALUE pairs for {key} placeholder substitution.
        """
        ensure_agent_browser_installed()

        cmds_dir = get_browser_cmds_dir()
        cmd_path = cmds_dir / cmd_name
        cmd = BrowserCmd.from_path(cmd_path)

        if cmd is None:
            click.echo(f"Error: Browser command '{cmd_name}' not found in {cmds_dir}", err=True)
            sys.exit(1)

        # Parse params
        param_dict: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.ClickException(f"Invalid parameter format: '{p}' (expected KEY=VALUE)")
            key, value = p.split("=", 1)
            param_dict[key] = value

        # Check required params
        for p in cmd.parameters:
            pname = p.get("name", "")
            if p.get("required", False) and pname not in param_dict:
                default = p.get("default")
                if default is not None:
                    param_dict[pname] = str(default)
                else:
                    raise click.ClickException(
                        f"Required parameter '{pname}' not provided. "
                        f"Use: {pname}=<value>"
                    )
            elif pname not in param_dict and "default" in p:
                param_dict[pname] = str(p["default"])

        instructions_raw = cmd.get_instructions()
        if not instructions_raw:
            raise click.ClickException(f"Command '{cmd_name}' has no instructions.")

        # Inject {clipboard} if used anywhere — quoted so shlex.split treats it as one token
        _PLACEHOLDER_RE = __import__("re").compile(r"\{(\w+)\}")
        _shlex = __import__("shlex")
        uses_clipboard = any(
            m.group(1) == "clipboard"
            for line in instructions_raw
            for m in _PLACEHOLDER_RE.finditer(line)
        )
        if uses_clipboard:
            param_dict["clipboard"] = _shlex.quote(read_clipboard())

        # Substitute params
        instructions = []
        for line in instructions_raw:
            instructions.append(substitute_params(line, param_dict))

        if dry_run:
            click.echo(f"Command: {cmd_name}")
            if cmd.description:
                click.echo(f"Description: {cmd.description}")
            click.echo(f"Instructions ({len(instructions)}):")
            for i, inst in enumerate(instructions, 1):
                click.echo(f"  [{i}] {inst}")
            return

        # Browser lifecycle
        launched_browser = False
        if not is_cdp_available(cdp_port) and not no_auto_browser:
            launched_browser = True
            _launch_browser(cdp_port)

        import json

        results = []
        errors = []

        try:
            for i, instruction in enumerate(instructions):
                if fmt == "text":
                    click.echo(f"  [{i + 1}/{len(instructions)}] {instruction}", err=True)

                try:
                    result = run_agent_cmd(instruction, cdp_port, timeout=timeout)
                except Exception as exc:
                    entry = {
                        "instruction": instruction,
                        "stdout": "",
                        "stderr": str(exc),
                        "exit_code": 1,
                        "success": False,
                    }
                    results.append(entry)
                    errors.append(entry)
                    if fmt == "text":
                        click.echo(f"    Error: {exc}", err=True)
                    continue

                entry = {
                    "instruction": instruction,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "exit_code": result.returncode,
                    "success": result.returncode == 0,
                }
                results.append(entry)

                if fmt == "text" and entry["success"] and entry["stdout"]:
                    click.echo(entry["stdout"])
                if entry["exit_code"] != 0:
                    errors.append(entry)
                    if fmt == "text" and entry["stderr"]:
                        click.echo(f"    Error: {entry['stderr']}", err=True)

        finally:
            if launched_browser and not keep_browser:
                _stop_browser(cdp_port)
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
