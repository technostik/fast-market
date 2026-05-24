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
from core.browser_cmd import BrowserCmd, discover_browser_cmds


# ---------------------------------------------------------------------------
# Help text
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
  /help             Show this help
  /apply <name>     Load and run a stored command, adding its steps to history
  /history          List instructions in this session
  /clear            Clear session history (keeps browser open)
  /save             Interactively pick steps and save as a reusable command
  /exit             Exit (Ctrl+D also works)
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

_REPL_CMDS = ["/help", "/apply", "/history", "/clear", "/save", "/exit"]


# ---------------------------------------------------------------------------
# Custom completer: context-aware for /apply <name> and browser instructions
# ---------------------------------------------------------------------------

def _make_completer():
    from prompt_toolkit.completion import Completer, Completion, WordCompleter

    browser_completer = WordCompleter(_BROWSER_CMDS, ignore_case=True, sentence=True)
    repl_completer = WordCompleter(_REPL_CMDS, ignore_case=True, sentence=True)

    class _ReplCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor

            if text.startswith("/apply "):
                # Complete with stored browser command names
                word = text[len("/apply "):].lstrip()
                try:
                    cmds = discover_browser_cmds(get_browser_cmds_dir())
                except Exception:
                    cmds = []
                for cmd in cmds:
                    if cmd.name.startswith(word):
                        yield Completion(
                            cmd.name,
                            start_position=-len(word),
                            display_meta=cmd.description or "",
                        )
            elif text.startswith("/"):
                yield from repl_completer.get_completions(document, complete_event)
            else:
                yield from browser_completer.get_completions(document, complete_event)

    return _ReplCompleter()


# ---------------------------------------------------------------------------
# Interactive step picker for /save
# ---------------------------------------------------------------------------

def _pick_steps(history: list[str]) -> list[str] | None:
    """Show a TUI checklist to select which steps to save.

    Returns the selected steps, or None if cancelled.
    Keys: ↑↓ move · Space/X toggle · Enter confirm · Q/Esc cancel
    """
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    checked = [True] * len(history)
    state = {"cursor": 0, "cancelled": False}

    def render():
        lines: list[tuple[str, str]] = []
        lines.append(("bold", "  Select steps   ↑↓ move · Space/X toggle · Enter save · Q cancel\n\n"))
        for i, inst in enumerate(history):
            mark = "✓" if checked[i] else " "
            at_cursor = i == state["cursor"]
            if at_cursor:
                lines.append(("fg:ansiblack bg:ansigreen bold", f" ▶ [{mark}] {inst} \n"))
            elif checked[i]:
                lines.append(("", f"   [{mark}] {inst}\n"))
            else:
                lines.append(("fg:ansidarkgray", f"   [ ] {inst}\n"))
        n_sel = sum(checked)
        lines.append(("italic", f"\n  {n_sel}/{len(history)} selected\n"))
        return FormattedText(lines)

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        state["cursor"] = max(0, state["cursor"] - 1)
        event.app.invalidate()

    @kb.add("down")
    def _(event):
        state["cursor"] = min(len(history) - 1, state["cursor"] + 1)
        event.app.invalidate()

    @kb.add("space")
    @kb.add("x")
    @kb.add("X")
    def _(event):
        checked[state["cursor"]] = not checked[state["cursor"]]
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        event.app.exit()

    @kb.add("q")
    @kb.add("Q")
    @kb.add("escape")
    @kb.add("c-c")
    def _(event):
        state["cancelled"] = True
        event.app.exit()

    control = FormattedTextControl(render, focusable=True)
    layout = Layout(Window(content=control))
    app = Application(layout=layout, key_bindings=kb, full_screen=False, mouse_support=False)
    app.run()

    if state["cancelled"]:
        return None

    return [inst for i, inst in enumerate(history) if checked[i]]


# ---------------------------------------------------------------------------
# /save helper
# ---------------------------------------------------------------------------

def _save_session(history: list[str], default_name: str = "") -> None:
    """Pick steps interactively then save as a named browser command."""
    import shutil
    import yaml
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter

    if not history:
        click.echo("No instructions in history to save.")
        return

    # Step 1: interactive picker
    click.echo()
    selected = _pick_steps(history)
    click.echo()  # blank line after TUI

    if selected is None:
        click.echo("Save cancelled.")
        return

    if not selected:
        click.echo("No steps selected — save cancelled.")
        return

    # Step 2: name
    existing_names = [c.name for c in discover_browser_cmds(get_browser_cmds_dir())]
    name_completer = WordCompleter(existing_names, ignore_case=False)
    try:
        name = pt_prompt(
            "Command name: ",
            default=default_name,
            completer=name_completer,
        ).strip()
    except (KeyboardInterrupt, EOFError):
        click.echo("\nSave cancelled.")
        return

    if not name:
        click.echo("Save cancelled (no name given).")
        return

    # Step 3: description (pre-fill from existing command if updating)
    existing_desc = ""
    cmds_dir = get_browser_cmds_dir()
    cmd_dir = cmds_dir / name
    if cmd_dir.exists():
        existing = BrowserCmd.from_path(cmd_dir)
        if existing:
            existing_desc = existing.description or ""

    try:
        description = pt_prompt("Description: ", default=existing_desc).strip()
    except (KeyboardInterrupt, EOFError):
        description = existing_desc

    # Step 4: overwrite if needed
    if cmd_dir.exists():
        try:
            ans = pt_prompt(f"'{name}' already exists. Overwrite? [Y/n]: ", default="y").strip().lower()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nSave cancelled.")
            return
        if ans not in ("", "y", "yes"):
            click.echo("Save cancelled.")
            return
        shutil.rmtree(cmd_dir)

    # Step 5: write
    cmd_dir.mkdir(parents=True)
    cmd_file = cmd_dir / "COMMAND.md"
    frontmatter = {"name": name, "description": description, "parameters": []}
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    body = "\n".join(selected)
    cmd_file.write_text(f"---\n{fm_str}---\n{body}\n", encoding="utf-8")

    click.echo(f"Saved '{name}' ({len(selected)} step(s)).")
    click.echo(f"  browser apply {name}")
    click.echo(f"  browser cmd edit {name}")


# ---------------------------------------------------------------------------
# Browser lifecycle helpers
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
# /apply helper: run a stored command and append its steps to history
# ---------------------------------------------------------------------------

def _run_apply(cmd_name: str, cdp_port: int, timeout: int | None, history: list[str]) -> str | None:
    """Load and execute a stored browser command, appending steps to history.

    Returns the command name on success, None if the command was not found.
    """
    cmds_dir = get_browser_cmds_dir()
    cmd = BrowserCmd.from_path(cmds_dir / cmd_name)
    if cmd is None:
        click.echo(f"Command '{cmd_name}' not found.", err=True)
        return None

    instructions = cmd.get_instructions()
    if not instructions:
        click.echo(f"Command '{cmd_name}' has no instructions.", err=True)
        return cmd_name

    click.echo(f"Applying '{cmd_name}' ({len(instructions)} step(s))…")

    for i, inst in enumerate(instructions):
        click.echo(f"  [{i + 1}/{len(instructions)}] {inst}", err=True)
        history.append(inst)
        try:
            result = run_agent_cmd(inst, cdp_port, timeout=timeout)
        except Exception as exc:
            click.echo(f"    Error: {exc}", err=True)
            continue
        if result.stdout.strip():
            click.echo(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            click.echo(f"    Error: {result.stderr.strip()}", err=True)

    return cmd_name


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------

def _run_repl(cdp_port: int, timeout: int | None) -> None:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style

    style = Style.from_dict({"prompt": "ansigreen bold"})

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        completer=_make_completer(),
        style=style,
        complete_while_typing=False,
    )

    history: list[str] = []        # all instructions added this session
    last_applied: str = ""         # name of last /apply-ed command (default for /save)

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

        # ---- REPL slash commands ----
        if line.startswith("/"):
            parts = line.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "/exit":
                break

            elif cmd == "/help":
                click.echo(_HELP_TEXT)

            elif cmd == "/apply":
                if not arg:
                    click.echo("Usage: /apply <command-name>", err=True)
                else:
                    result_name = _run_apply(arg, cdp_port, timeout, history)
                    if result_name:
                        last_applied = result_name

            elif cmd == "/history":
                if not history:
                    click.echo("No instructions yet.")
                else:
                    for i, inst in enumerate(history, 1):
                        click.echo(f"  [{i:2}] {inst}")

            elif cmd == "/clear":
                history.clear()
                last_applied = ""
                click.echo("Session history cleared.")

            elif cmd == "/save":
                _save_session(history, default_name=last_applied)

            else:
                click.echo(f"Unknown REPL command: {cmd}  (try /help)")

            continue

        # ---- Browser instruction ----
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

        Type agent-browser instructions one per line and see results.
        Use /apply <name> to run a stored command and extend it.
        Use /save to pick steps and save as a reusable command.
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
