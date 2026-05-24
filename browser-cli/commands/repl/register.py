from __future__ import annotations

import time
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    run_agent_cmd,
)
from common.core.paths import get_browser_cmds_dir
from core.browser_cmd import _COMMAND_TEMPLATE, BrowserCmd, discover_browser_cmds


# ---------------------------------------------------------------------------
# Compact help text built from the agent-browser.md command table
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
Browser instructions (omit the 'agent-browser' prefix):

  NAVIGATION   open <url>   back   forward   reload   close
  INTERACT     click <sel>   dblclick <sel>   hover <sel>
               fill <sel> <text>   type <sel> <text>   press <key>
               scroll <dir> [px]   drag <src> <tgt>   upload <sel> <file>
  INSPECT      snapshot   get title   get url   get text <sel>
               screenshot [path]   get html <sel>   get value <sel>
  FIND         find role <role> <action>   find text <text> <action>
               find label <label> <action>   find first <sel> <action>
  WAIT         wait <sel>   wait <ms>   wait --text "..."   wait --url "..."
  TABS         tab   tab new [url]   tab <n>   tab close [n]
  STATE        state save <path>   state load <path>   state list
  DEBUG        console   errors   eval <js>   highlight <sel>

REPL commands:
  /help        Show this help
  /history     List instructions typed this session
  /clear       Clear session history (keeps browser open)
  /save        Save session instructions as a reusable browser command
  /exit        Exit (Ctrl+D also works)
"""

# Top-level agent-browser commands for tab-completion
_BROWSER_CMDS = [
    "open", "navigate", "goto", "back", "forward", "reload", "close",
    "click", "dblclick", "fill", "type", "press", "hover", "focus",
    "scroll", "scrollintoview", "drag", "upload", "check", "uncheck",
    "select", "keydown", "keyup",
    "snapshot", "screenshot", "pdf",
    "get", "is", "find", "wait",
    "tab", "frame", "dialog",
    "eval", "console", "errors", "highlight", "inspect",
    "state", "cookies", "storage", "network",
    "mouse", "keyboard", "clipboard",
    "diff", "trace", "profiler", "batch", "set",
]

_REPL_CMDS = ["/help", "/history", "/clear", "/save", "/exit"]


# ---------------------------------------------------------------------------
# Browser lifecycle helpers (same logic as run/script commands)
# ---------------------------------------------------------------------------

def _launch_browser(cdp_port: int) -> None:
    import subprocess

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
    for finder in [
        ["lsof", "-ti", f"TCP:*:{cdp_port}"],
        ["pgrep", "-f", f"--remote-debugging-port={cdp_port}"],
    ]:
        try:
            r = subprocess.run(finder, capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                pids = [int(p) for p in r.stdout.strip().split("\n")]
                break
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
# /save helper
# ---------------------------------------------------------------------------

def _save_session(history: list[str]) -> None:
    """Interactively save the session history as a named browser command."""
    from prompt_toolkit import prompt as pt_prompt

    if not history:
        click.echo("No instructions in history to save.")
        return

    click.echo("\nInstructions to save:")
    for i, inst in enumerate(history, 1):
        click.echo(f"  [{i}] {inst}")

    click.echo()

    try:
        name = pt_prompt("Command name: ").strip()
    except (KeyboardInterrupt, EOFError):
        click.echo("\nSave cancelled.")
        return

    if not name:
        click.echo("Save cancelled (no name given).")
        return

    try:
        description = pt_prompt("Description (optional): ").strip()
    except (KeyboardInterrupt, EOFError):
        description = ""

    cmds_dir = get_browser_cmds_dir()
    cmd_dir = cmds_dir / name

    if cmd_dir.exists():
        try:
            overwrite = pt_prompt(f"Command '{name}' already exists. Overwrite? [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nSave cancelled.")
            return
        if overwrite not in ("y", "yes"):
            click.echo("Save cancelled.")
            return
        import shutil
        shutil.rmtree(cmd_dir)

    cmd_dir.mkdir(parents=True)
    cmd_file = cmd_dir / "COMMAND.md"

    body = "\n".join(history)
    content = _COMMAND_TEMPLATE.format(name=name)

    # Build frontmatter properly
    import yaml
    frontmatter = {"name": name, "description": description, "parameters": []}
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n{body}\n"
    cmd_file.write_text(content, encoding="utf-8")

    click.echo(f"\nSaved as '{name}' ({len(history)} instruction(s)).")
    click.echo(f"Run with: browser apply {name}")
    click.echo(f"Edit with: browser cmd edit {name}")


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------

def _run_repl(cdp_port: int, timeout: int | None) -> None:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style

    style = Style.from_dict({
        "prompt": "ansigreen bold",
    })

    all_words = _BROWSER_CMDS + _REPL_CMDS
    completer = WordCompleter(all_words, ignore_case=True, sentence=True)

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        completer=completer,
        style=style,
        complete_while_typing=False,
    )

    # Session instruction history (for /save)
    history: list[str] = []

    click.echo("Browser REPL — type instructions or /help. Ctrl+D to exit.")
    click.echo()

    while True:
        try:
            line = session.prompt([("class:prompt", "browser> ")]).strip()
        except KeyboardInterrupt:
            click.echo()
            continue
        except EOFError:
            click.echo()
            break

        if not line:
            continue

        # --- REPL commands ---
        if line.startswith("/"):
            cmd = line.split()[0].lower()

            if cmd == "/exit":
                break

            elif cmd == "/help":
                click.echo(_HELP_TEXT)

            elif cmd == "/history":
                if not history:
                    click.echo("No instructions yet.")
                else:
                    for i, inst in enumerate(history, 1):
                        click.echo(f"  [{i}] {inst}")

            elif cmd == "/clear":
                history.clear()
                click.echo("Session history cleared.")

            elif cmd == "/save":
                _save_session(history)

            else:
                click.echo(f"Unknown REPL command: {cmd}  (try /help)")

            continue

        # --- Browser instruction ---
        history.append(line)

        try:
            result = run_agent_cmd(line, cdp_port, timeout=timeout)
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            continue

        if result.stdout.strip():
            click.echo(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            click.echo(f"Error: {result.stderr.strip()}", err=True)


# ---------------------------------------------------------------------------
# Click command registration
# ---------------------------------------------------------------------------

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("repl")
    @click.option("--cdp-port", type=int, default=9222, show_default=True, help="Chrome DevTools Protocol port.")
    @click.option("--keep-browser", "-k", is_flag=True, help="Do not stop the browser when the REPL exits.")
    @click.option("--timeout", "-t", type=int, default=None, help="Timeout per instruction in milliseconds.")
    @click.option("--no-auto-browser", is_flag=True, help="Do not auto-launch browser if none is running.")
    def repl_cmd(cdp_port, keep_browser, timeout, no_auto_browser):
        """Start an interactive browser REPL.

        Type agent-browser instructions one per line and see the results.
        Use /save to store the session commands as a reusable browser command.
        """
        ensure_agent_browser_installed()

        launched_browser = False
        if not is_cdp_available(cdp_port) and not no_auto_browser:
            launched_browser = True
            _launch_browser(cdp_port)

        try:
            _run_repl(cdp_port, timeout)
        finally:
            if launched_browser and not keep_browser:
                _stop_browser(cdp_port)
                click.echo("Browser stopped.", err=True)

    return CommandManifest(name="repl", click_command=repl_cmd)
