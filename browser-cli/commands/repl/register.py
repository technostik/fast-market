from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.helpers import (
    ensure_agent_browser_installed,
    is_cdp_available,
    read_clipboard,
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

Placeholders: use {name} anywhere in an instruction.
  {clipboard}  always resolves to the current clipboard content
  {anything}   prompts for a value on first use, then remembers it

REPL commands:
  /help             Show this help
  /apply <name>     Load and run a stored command, adding its steps to history
  /params           Show (and optionally clear) current session params
  /history          List instructions in this session
  /clear            Clear history and session params
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

_REPL_CMDS = ["/help", "/apply", "/params", "/history", "/clear", "/save", "/exit"]

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------

def _resolve(text: str, params: dict[str, str]) -> tuple[str, bool]:
    """Substitute all {name} placeholders in *text*.

    {clipboard} is always read fresh.
    All other names are looked up in *params*; if missing the user is prompted
    and the value is stored in *params* for reuse.

    Values are wrapped with shlex.quote() so that multi-word / multiline content
    (e.g. clipboard text) is passed as a single argument after shlex.split().

    Returns (resolved_text, was_substituted).
    """
    from prompt_toolkit import prompt as pt_prompt

    substituted = False

    def replace(match: re.Match) -> str:
        nonlocal substituted
        key = match.group(1)

        if key == "clipboard":
            val = read_clipboard()
            substituted = True
            return shlex.quote(val)

        if key in params:
            substituted = True
            return shlex.quote(params[key])

        # Prompt the user
        try:
            val = pt_prompt(f"  {key}: ").strip()
        except (KeyboardInterrupt, EOFError):
            raise click.ClickException(f"Parameter '{key}' not provided — instruction skipped.")

        params[key] = val
        substituted = True
        return shlex.quote(val)

    result = _PLACEHOLDER_RE.sub(replace, text)
    return result, substituted


def _detect_placeholder_names(instructions: list[str]) -> list[str]:
    """Return unique placeholder names found in instructions (excluding 'clipboard')."""
    seen: set[str] = set()
    names: list[str] = []
    for inst in instructions:
        for m in _PLACEHOLDER_RE.finditer(inst):
            name = m.group(1)
            if name != "clipboard" and name not in seen:
                seen.add(name)
                names.append(name)
    return names


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
    """TUI checklist to select which steps to include in the saved command.

    Returns selected steps or None if cancelled.
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
        lines: list[tuple[str, str]] = [
            ("bold", "  Select steps   ↑↓ move · Space/X toggle · Enter save · Q cancel\n\n"),
        ]
        for i, inst in enumerate(history):
            mark = "✓" if checked[i] else " "
            if i == state["cursor"]:
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

    layout = Layout(Window(FormattedTextControl(render, focusable=True)))
    Application(layout=layout, key_bindings=kb, full_screen=False, mouse_support=False).run()

    if state["cancelled"]:
        return None
    return [inst for i, inst in enumerate(history) if checked[i]]


# ---------------------------------------------------------------------------
# /save helper
# ---------------------------------------------------------------------------

def _save_session(
    history: list[str],
    params: dict[str, str],
    default_name: str = "",
) -> None:
    """Pick steps interactively, then write them as a named browser command."""
    import shutil
    import yaml
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter

    if not history:
        click.echo("No instructions in history to save.")
        return

    click.echo()
    selected = _pick_steps(history)
    click.echo()

    if selected is None:
        click.echo("Save cancelled.")
        return
    if not selected:
        click.echo("No steps selected — save cancelled.")
        return

    # Name (tab-completes existing commands; pre-fills last applied name)
    existing_names = [c.name for c in discover_browser_cmds(get_browser_cmds_dir())]
    try:
        name = pt_prompt(
            "Command name: ",
            default=default_name,
            completer=WordCompleter(existing_names, ignore_case=False),
        ).strip()
    except (KeyboardInterrupt, EOFError):
        click.echo("\nSave cancelled.")
        return
    if not name:
        click.echo("Save cancelled (no name given).")
        return

    cmds_dir = get_browser_cmds_dir()
    cmd_dir = cmds_dir / name

    # Pre-fill description from existing command if overwriting
    existing_desc = ""
    if cmd_dir.exists():
        existing = BrowserCmd.from_path(cmd_dir)
        if existing:
            existing_desc = existing.description or ""

    try:
        description = pt_prompt("Description: ", default=existing_desc).strip()
    except (KeyboardInterrupt, EOFError):
        description = existing_desc

    # Overwrite check
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

    # Auto-detect parameters used in selected steps
    param_names = _detect_placeholder_names(selected)
    parameters = []
    for pname in param_names:
        entry: dict = {"name": pname, "description": "", "required": True}
        if pname in params:
            entry["default"] = params[pname]
        parameters.append(entry)

    # Write COMMAND.md
    cmd_dir.mkdir(parents=True)
    frontmatter = {"name": name, "description": description, "parameters": parameters}
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    body = "\n".join(selected)
    (cmd_dir / "COMMAND.md").write_text(f"---\n{fm_str}---\n{body}\n", encoding="utf-8")

    click.echo(f"Saved '{name}' ({len(selected)} step(s)).", err=False)
    if parameters:
        pnames = ", ".join(p["name"] for p in parameters)
        click.echo(f"  Parameters detected: {pnames}")
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
    click.echo(f"Launching browser on CDP port {cdp_port}…", err=True)
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
# /apply: run a stored command, resolve its params, append steps to history
# ---------------------------------------------------------------------------

def _run_apply(
    cmd_name: str,
    cdp_port: int,
    timeout: int | None,
    history: list[str],
    params: dict[str, str],
) -> str | None:
    """Load and execute a stored command.

    Parameters declared in its frontmatter are resolved from *params* or
    prompted if missing.  Each instruction (with original placeholders) is
    appended to *history*.

    Returns the command name on success, None if not found.
    """
    from prompt_toolkit import prompt as pt_prompt

    cmds_dir = get_browser_cmds_dir()
    cmd = BrowserCmd.from_path(cmds_dir / cmd_name)
    if cmd is None:
        click.echo(f"Command '{cmd_name}' not found.", err=True)
        return None

    instructions = cmd.get_instructions()
    if not instructions:
        click.echo(f"Command '{cmd_name}' has no instructions.", err=True)
        return cmd_name

    # Resolve declared parameters first (so we know defaults / required status)
    for p in cmd.parameters:
        pname = p.get("name", "")
        if not pname:
            continue
        if pname in params:
            continue  # already set in session

        default = str(p.get("default", "")) if "default" in p else ""
        required = p.get("required", True)
        desc = p.get("description", "")
        label = f"  {pname}"
        if desc:
            label += f" ({desc})"
        label += ": "

        try:
            val = pt_prompt(label, default=default).strip()
        except (KeyboardInterrupt, EOFError):
            if not required and default:
                val = default
            else:
                click.echo(f"\n  Skipped '{pname}' — using empty string.", err=True)
                val = ""

        params[pname] = val

    click.echo(f"Applying '{cmd_name}' ({len(instructions)} step(s))…")

    for i, raw_inst in enumerate(instructions):
        # Append original (with placeholders) to history
        history.append(raw_inst)

        # Resolve placeholders for execution
        try:
            resolved, was_sub = _resolve(raw_inst, params)
        except click.ClickException as exc:
            click.echo(f"  [{i + 1}] {raw_inst}", err=True)
            click.echo(f"    Error: {exc.format_message()}", err=True)
            continue

        display = resolved.replace("\n", "\\n").replace("\r", "\\r")
        click.echo(f"  [{i + 1}/{len(instructions)}] {display}", err=True)

        try:
            result = run_agent_cmd(resolved, cdp_port, timeout=timeout)
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

def _run_repl(cdp_port: int, timeout: int | None, initial_params: dict[str, str] | None = None) -> None:
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

    history: list[str] = []                          # raw instructions (with placeholders preserved)
    params: dict[str, str] = dict(initial_params or {})  # session-level param store
    last_applied: str = ""                           # for /save default name

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
                    result_name = _run_apply(arg, cdp_port, timeout, history, params)
                    if result_name:
                        last_applied = result_name

            elif cmd == "/params":
                if not params:
                    click.echo("No session params set.")
                else:
                    click.echo("Session params:")
                    for k, v in params.items():
                        click.echo(f"  {k} = {v!r}")
                    try:
                        from prompt_toolkit import prompt as pt_prompt
                        ans = pt_prompt("Clear all params? [y/N]: ", default="n").strip().lower()
                        if ans in ("y", "yes"):
                            params.clear()
                            click.echo("Params cleared.")
                    except (KeyboardInterrupt, EOFError):
                        click.echo()

            elif cmd == "/history":
                if not history:
                    click.echo("No instructions yet.")
                else:
                    for i, inst in enumerate(history, 1):
                        click.echo(f"  [{i:2}] {inst}")

            elif cmd == "/clear":
                history.clear()
                params.clear()
                last_applied = ""
                click.echo("History and params cleared.")

            elif cmd == "/save":
                _save_session(history, params, default_name=last_applied)

            else:
                click.echo(f"Unknown REPL command: {cmd}  (try /help)")

            continue

        # ---- Browser instruction ----
        # Store original (with placeholders) in history
        history.append(line)

        # Resolve placeholders
        try:
            resolved, was_sub = _resolve(line, params)
        except click.ClickException as exc:
            click.echo(f"Error: {exc.format_message()}", err=True)
            continue

        if was_sub and resolved != line:
            display = resolved.replace("\n", "\\n").replace("\r", "\\r")
            click.echo(f"  → {display}", err=True)

        try:
            result = run_agent_cmd(resolved, cdp_port, timeout=timeout)
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
    @click.option(
        "--param", "-p",
        "params",
        multiple=True,
        metavar="KEY=VALUE",
        help="Pre-set a placeholder value (can repeat). e.g. -p url=https://x.com",
    )
    def repl_cmd(cdp_port, keep_browser, timeout, no_auto_browser, params):
        """Start an interactive browser REPL.

        Type agent-browser instructions one per line.  Use {name} placeholders
        in any instruction — {clipboard} reads the system clipboard, others
        prompt on first use and are remembered for the session.

        Pre-seed placeholder values with -p KEY=VALUE so they are available
        immediately without prompting.

        Use /apply <name> to run a stored command and extend it.
        Use /save to pick steps and save as a reusable command.
        """
        ensure_agent_browser_installed()

        initial_params: dict[str, str] = {}
        for p in params:
            if "=" not in p:
                raise click.BadParameter(f"Expected KEY=VALUE, got: {p!r}", param_hint="-p")
            key, value = p.split("=", 1)
            initial_params[key] = value

        launched_browser = False
        if not is_cdp_available(cdp_port) and not no_auto_browser:
            launched_browser = True
            _launch_browser(cdp_port)

        try:
            _run_repl(cdp_port, timeout, initial_params)
        finally:
            if launched_browser and not keep_browser:
                _stop_browser(cdp_port)
                click.echo("Browser stopped.", err=True)

    return CommandManifest(name="repl", click_command=repl_cmd)
