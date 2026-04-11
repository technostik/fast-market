"""``browser run`` — LLM-driven browser automation.

Launches an agentic loop where the LLM has a single ``browse`` tool to
accomplish a task.  The full ``agent-browser`` documentation is included
in the system prompt so the model knows every available sub-command.

Usage::

    browser run "go to example.com and tell me the title"
    browser run "upload {video_file} to https://example.com/upload" -p video_file=/path/to.mp4
    browser run --file task.txt -p url=https://example.com
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
)
from commands.run.session_utils import export_data_to_session_dict
from common.core.config import load_tool_config, get_tool_config_path, ConfigError
from common.llm.registry import get_default_provider_name


class _ProviderParamType(click.ParamType):
    """Shell completion for LLM provider names."""
    name = "provider"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list:
        try:
            from click.shell_completion import CompletionItem
            config = load_tool_config("apply")
            providers = {}
            try:
                from common.llm.registry import discover_providers
                providers = discover_providers(config)
            except Exception:
                pass
            completions = []
            for name in providers.keys():
                if incomplete.lower() in name.lower():
                    completions.append(CompletionItem(name, help=f"Provider: {name}"))
            return completions
        except Exception:
            return []


def _load_browser_doc() -> str:
    """Load the full agent-browser documentation, stripped of the ``agent-browser `` prefix."""
    doc_path = Path(__file__).resolve().parents[2] / "agent-browser.md"
    if not doc_path.exists():
        raise click.ClickException(f"Browser documentation not found: {doc_path}")
    content = doc_path.read_text()
    # Strip leading "agent-browser " from command lines (same as ``browser doc``)
    content = re.sub(r"^(\s*)agent-browser\s+", r"\1", content, flags=re.MULTILINE)
    return content


def _resolve_params(params: tuple[str, ...], workdir: Path) -> dict[str, str]:
    """Resolve task parameters from ``--param`` arguments.

    Values can be:
    - Literal string: ``key=value``
    - Stdin: ``key=@-`` (reads from stdin)
    - File: ``key=@filename`` (reads from file, resolved against *workdir*)
    """
    result = {}
    for p in params:
        if "=" not in p:
            raise click.ClickException(
                f"Invalid parameter format: '{p}' (expected KEY=VALUE)"
            )
        key, value = p.split("=", 1)

        if value == "@-":
            if sys.stdin.isatty():
                raise click.ClickException(
                    f"Parameter '{key}' requires stdin input but none available"
                )
            result[key] = sys.stdin.read().strip()
        elif value.startswith("@"):
            filepath = workdir / value[1:]
            if not filepath.exists():
                raise click.ClickException(
                    f"Parameter '{key}': file not found: {filepath}"
                )
            result[key] = filepath.read_text(encoding="utf-8").strip()
        else:
            result[key] = value

    return result


def _validate_workdir(path: str) -> Path:
    """Resolve and validate a working directory."""
    p = Path(path).expanduser().resolve()
    forbidden = {
        Path("/"), Path("/bin"), Path("/sbin"), Path("/usr"),
        Path("/lib"), Path("/lib64"), Path("/etc"),
        Path("/sys"), Path("/proc"), Path("/dev"),
    }
    if p in forbidden:
        raise click.ClickException(
            f"Refusing to use sensitive directory as workdir: {p}"
        )
    return p


# ---------------------------------------------------------------------------
# Browser lifecycle helpers
# ---------------------------------------------------------------------------

def _launch_browser(cdp_port: int, user_data_dir: str | None = None) -> None:
    """Launch Chromium with CDP enabled in the background."""
    import subprocess
    import os

    browser_bin = "google-chrome"
    if user_data_dir is None:
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

    # Wait for browser to be ready (up to 15 s)
    for _ in range(30):
        if is_cdp_available(cdp_port):
            return
        time.sleep(0.5)

    click.echo(
        f"Warning: Browser may not have started on port {cdp_port}.",
        err=True,
    )


def _stop_browser(cdp_port: int) -> None:
    """Stop the browser process on the given CDP port."""
    import signal
    import subprocess
    import os

    pids: list[int] = []
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


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("run")
    @click.argument("task_description", required=False)
    @click.option(
        "--file",
        "-f",
        "task_file",
        type=click.Path(exists=True),
        default=None,
        help="Load task description from file.",
    )
    @click.option(
        "--workdir",
        "-w",
        default=None,
        help="Working directory (default: from config or CWD).",
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
        "--provider",
        "-P",
        type=_ProviderParamType(),
        default=None,
        help="LLM provider to use.",
    )
    @click.option(
        "--model", "-m", default=None, help="Override default model."
    )
    @click.option(
        "--max-iterations",
        "-i",
        type=int,
        default=None,
        help="Max LLM turns before stopping (default: 20).",
    )
    @click.option(
        "--timeout",
        "-t",
        type=int,
        default=None,
        help="Timeout per browser action in seconds (default: 60).",
    )
    @click.option(
        "--llm-timeout",
        type=int,
        default=0,
        help="Timeout per LLM call in seconds, 0 = no limit.",
    )
    @click.option(
        "--cdp-port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port.",
    )
    @click.option(
        "--keep-browser",
        "-k",
        is_flag=True,
        help="Do not stop the browser after the task completes.",
    )
    @click.option(
        "--user-data-dir",
        "-u",
        default=None,
        help="Chrome user data directory (default: ~/.chrome-debug-profile).",
    )
    @click.option(
        "--no-auto-browser",
        is_flag=True,
        help="Do not auto-launch browser if none is running.",
    )
    @click.option(
        "--debug", "-d", type=str, default="", help="Debug: 'normal' or 'full'."
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["text", "json"]),
        default="text",
        help="Output format.",
    )
    @click.option(
        "--silent",
        "-s",
        is_flag=True,
        help="Suppress session output.",
    )
    @click.option(
        "--save-session",
        "-o",
        type=click.Path(),
        default=None,
        help="Save session to YAML file.",
    )
    @click.option(
        "--export",
        "-e",
        "export_path",
        type=click.Path(),
        default=None,
        help="Export session as YAML with commands and results for LLM learning.",
    )
    @click.option(
        "--commands-only",
        "-c",
        is_flag=True,
        help="When used with --export, export only the command sequence (no stdout/results).",
    )
    @click.option(
        "--import",
        "-I",
        "import_path",
        type=click.Path(exists=True),
        default=None,
        help="Import a previous session export to inform the agent.",
    )
    @click.pass_context
    def run_cmd(
        ctx,
        task_description: str | None,
        task_file: str | None,
        workdir: str | None,
        params: tuple[str, ...],
        provider: str | None,
        model: str | None,
        max_iterations: int | None,
        timeout: int | None,
        llm_timeout: int,
        cdp_port: int,
        keep_browser: bool,
        user_data_dir: str | None,
        no_auto_browser: bool,
        debug: str,
        fmt: str,
        silent: bool,
        save_session: str | None,
        export_path: str | None,
        commands_only: bool,
        import_path: str | None,
    ) -> None:
        """Run an LLM-driven browser task.

        TASK_DESCRIPTION describes what the agent should accomplish in the
        browser.  The LLM has access to a single ``browse`` tool that maps
        to all ``agent-browser`` sub-commands.

        Use ``-p KEY=VALUE`` to define ``{key}`` placeholders that can be used
        in the task description and browse tool args (e.g. file paths for
        upload).
        """
        if debug and debug not in ("normal", "full"):
            raise click.BadParameter("--debug must be 'normal' or 'full'", param_hint="--debug")

        ensure_agent_browser_installed()

        # Load common config
        common_config = load_tool_config("apply")

        # Resolve workdir
        resolved_workdir = (
            workdir
            or common_config.get("workdir")
            or "."
        )
        workdir_path = _validate_workdir(resolved_workdir)

        # Resolve save path
        if save_session is not None:
            save_path = Path(save_session)
            if save_path.is_absolute():
                save_session = str(save_path)
            else:
                save_session = str(workdir_path / save_path)
        else:
            save_session = str(workdir_path / ".last-browser-session.yaml")

        # Resolve task description
        if task_file:
            task_description = Path(task_file).read_text(encoding="utf-8").strip()
        if not task_description:
            raise click.ClickException(
                "TASK_DESCRIPTION is required (or use --file/-f)."
            )

        # Resolve parameters
        task_params = _resolve_params(params, workdir_path)

        # Resolve provider
        try:
            provider_name = provider or get_default_provider_name(common_config)
        except ConfigError:
            click.echo("Error: No default LLM provider configured.", err=True)
            click.echo("Run: task setup edit  (or task setup reset)", err=True)
            sys.exit(1)

        if not provider_name:
            click.echo("Error: No LLM provider available.", err=True)
            sys.exit(1)

        # Load browser documentation
        browser_doc = _load_browser_doc()

        # Load imported session if provided
        imported_session = None
        if import_path is not None:
            try:
                from common.agent.session import Session
                import_path_obj = Path(import_path)
                export_data = Session.load_export(import_path_obj)
                imported_session = Session.from_dict(
                    export_data_to_session_dict(export_data)
                )
                if not silent:
                    m = imported_session.metrics_dict()
                    click.echo(
                        f"Imported session: {imported_session.task_description[:80]}... "
                        f"({m['total_tool_calls']} commands, "
                        f"{m['error_count']} errors, "
                        f"{m['success_rate']:.0%} success)",
                        err=True,
                    )
            except Exception as exc:
                click.echo(f"Warning: Could not import session file: {exc}", err=True)

        # Browser lifecycle: auto-launch if needed
        launched_browser = False
        browser_was_running = is_cdp_available(cdp_port)

        if not browser_was_running and not no_auto_browser:
            launched_browser = True
            _launch_browser(cdp_port, user_data_dir)

        # Run the browser loop
        from commands.run.browser_loop import BrowserTaskLoop

        loop = BrowserTaskLoop(
            workdir=workdir_path,
            provider=provider_name,
            model=model,
            max_iterations=max_iterations or 20,
            default_timeout=timeout or 60,
            llm_timeout=llm_timeout,
            temperature=common_config.get("default_temperature", 0.3),
            cdp_port=cdp_port,
            verbose=ctx.obj.get("verbose", False),
            debug=debug,
            silent=silent,
            imported_session=imported_session,
        )

        try:
            loop.run(
                task_description=task_description,
                browser_doc=browser_doc,
                task_params=task_params,
            )

            # Save session
            if save_session and loop.session:
                session_path = Path(save_session)
                session_path.parent.mkdir(parents=True, exist_ok=True)
                loop.session.end_time = datetime.utcnow()
                loop.session.save(session_path)
                if not silent:
                    click.echo(f"\nSession saved to: {session_path}", err=True)

            # Export session (for LLM learning)
            if export_path and loop.session:
                export_path_obj = Path(export_path)
                if not export_path_obj.is_absolute():
                    export_path_obj = workdir_path / export_path_obj
                export_path_obj.parent.mkdir(parents=True, exist_ok=True)
                loop.session.end_time = datetime.utcnow()
                export_yaml = loop.session.to_export_yaml(commands_only=commands_only)
                export_path_obj.write_text(export_yaml, encoding="utf-8")
                label = "commands-only" if commands_only else "full"
                if not silent:
                    click.echo(f"\nSession exported ({label}) to: {export_path_obj}", err=True)

            # Metrics
            if not silent and loop.session:
                m = loop.session.metrics_dict()
                click.echo(
                    "\n── Session Metrics ──────────────────────────\n"
                    f"  Tool calls : {m['total_tool_calls']}\n"
                    f"  Rounds     : {m['iterations_used']}\n"
                    f"  Errors     : {m['error_count']}\n"
                    f"  Guesses    : {m['guess_count']}\n"
                    f"  Success    : {m['success_rate']:.0%}\n"
                    "────────────────────────────────────────────",
                    err=True,
                )

            if debug == "full" and not silent and loop.session:
                click.echo("\n" + "=" * 60, file=sys.stderr)
                click.echo("FULL SESSION YAML:", file=sys.stderr)
                click.echo(loop.session.to_yaml(), file=sys.stderr)

        except Exception as exc:
            if loop.session:
                loop.session.end_time = datetime.utcnow()
                loop.session.exit_code = 1
                loop.session.error = str(exc)
                loop.session.end_reason = f"internal failure: {exc}"
                if save_session:
                    session_path = Path(save_session)
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    loop.session.save(session_path)
                if export_path:
                    export_path_obj = Path(export_path)
                    if not export_path_obj.is_absolute():
                        export_path_obj = workdir_path / export_path_obj
                    export_path_obj.parent.mkdir(parents=True, exist_ok=True)
                    export_yaml = loop.session.to_export_yaml(commands_only=commands_only)
                    export_path_obj.write_text(export_yaml, encoding="utf-8")
                    label = "commands-only" if commands_only else "full"
                    click.echo(f"\nSession exported ({label}) to: {export_path_obj}", err=True)
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        finally:
            # Cleanup: stop browser if we launched it and --keep-browser not set
            if launched_browser and not keep_browser:
                _stop_browser(cdp_port)
                if not silent:
                    click.echo("Browser stopped.", err=True)

    return CommandManifest(
        name="run",
        click_command=run_cmd,
    )
