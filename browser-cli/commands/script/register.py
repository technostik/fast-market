from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    substitute_params,
    run_agent_cmd,
    out,
    read_stdin,
    is_cdp_available,
)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("script")
    @click.argument("script_input", required=False)
    @click.option(
        "--cdp-port",
        "-p",
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
        "-P",
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
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Read script from a file.",
    )
    @click.option(
        "--keep-browser",
        "-k",
        is_flag=True,
        help="Do not stop the browser after the script completes.",
    )
    def script_cmd(
        script_input: str | None,
        cdp_port: int,
        fmt: str,
        params: tuple[str, ...],
        stdin: bool,
        script_file: str | None,
        keep_browser: bool,
    ) -> None:
        """Run a set of agent-browser instructions as a script.

        SCRIPT_INPUT is either the script content (one instruction per line),
        a file path when using --file, or read from stdin with --stdin.

        Use -P KEY=VALUE to set {key} placeholders in the instructions.

        If no browser is detected on CDP, one is launched and stopped after
        the script finishes (unless --keep-browser is set).
        """
        ensure_agent_browser_installed()

        # Parse parameters
        param_dict: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.ClickException(f"Invalid parameter format: '{p}'. Use KEY=VALUE.")
            key, value = p.split("=", 1)
            param_dict[key] = value

        # Resolve script content
        if script_file:
            from pathlib import Path
            script_content = Path(script_file).read_text().strip()
        elif stdin or script_input == "-":
            script_content = read_stdin()
        elif script_input is None:
            raise click.ClickException("SCRIPT_INPUT is required (or use --stdin/-s or --file/-f).")
        else:
            script_content = script_input.strip()

        # Parse instructions (one per line, skip empty/comment lines)
        instructions = []
        for line in script_content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            instructions.append(line)

        if not instructions:
            raise click.ClickException("No instructions found in script.")

        # Track if we launched the browser ourselves
        launched_browser = False
        browser_was_running = is_cdp_available(cdp_port)

        if not browser_was_running:
            # Launch browser automatically
            import subprocess
            import os
            from pathlib import Path

            browser_bin = "google-chrome"
            user_data_dir = str(Path.home() / ".chrome-debug-profile")

            cmd = [
                browser_bin,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--disable-features=OptimizationHints",
            ]

            click.echo(f"No browser on CDP port {cdp_port}, launching {browser_bin}...", err=True)
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            # Wait for browser to be ready
            import time
            for _ in range(30):
                if is_cdp_available(cdp_port):
                    launched_browser = True
                    break
                time.sleep(0.5)
            else:
                click.echo(
                    f"Warning: Browser may not have started on port {cdp_port}.",
                    err=True,
                )

        # Execute instructions
        results = []
        errors = []
        for i, instruction in enumerate(instructions):
            # Substitute placeholders
            resolved = substitute_params(instruction, param_dict)

            if fmt == "text":
                click.echo(f"  [{i+1}/{len(instructions)}] {resolved}", err=True)

            result = run_agent_cmd(resolved, cdp_port)

            entry = {
                "instruction": resolved,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.returncode,
                "success": result.returncode == 0,
            }
            results.append(entry)

            if result.returncode != 0:
                errors.append(entry)
                if fmt == "text" and result.stderr.strip():
                    click.echo(f"    Error: {result.stderr.strip()}", err=True)

        # Cleanup: stop browser if we launched it and --keep-browser not set
        if launched_browser and not keep_browser:
            _stop_browser(cdp_port)
            if fmt == "text":
                click.echo("Browser stopped.", err=True)

        # Output results
        if fmt == "json":
            output = {
                "instructions": len(instructions),
                "errors": len(errors),
                "results": results,
            }
            out(output, fmt)
        else:
            if errors:
                click.echo(f"\n{len(errors)} error(s) in {len(instructions)} instruction(s).", err=True)
                raise SystemExit(1)
            else:
                click.echo(f"\n{len(instructions)} instruction(s) completed successfully.", err=True)

    return CommandManifest(
        name="script",
        click_command=script_cmd,
    )


def _stop_browser(cdp_port: int) -> None:
    """Stop the browser process on the given CDP port."""
    import signal
    import subprocess
    import time
    import os

    pids = []
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:*:{cdp_port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = [int(p.strip()) for p in result.stdout.strip().split("\n")]
    except (FileNotFoundError, ValueError):
        pass

    if not pids:
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"--remote-debugging-port={cdp_port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = [int(p.strip()) for p in result.stdout.strip().split("\n")]
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
