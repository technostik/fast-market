"""Startup-safe shell completion scripts.

A raw ``eval`` of ``browser`` on a terminal executes browser-use's welcome
text and the ``<<'PY'`` example in it, which launches Chrome.
"""

from __future__ import annotations

import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from commands.autocomplete.register import _generate_completion_script


QUICKSTART = """Welcome to the Browser Use CLI. Allow your coding agent to reliably control a web browser.

The CLI allows your agent to control the browser via Python.

  browser-use <<'PY'
  print(page_info())
  PY
"""


class CompletionScriptTests(unittest.TestCase):
    def test_bash_script_does_not_eval_raw_command_output(self):
        text = "\n".join(_generate_completion_script("bash", ["browser", "youtube"]))

        self.assertNotIn('eval "$(_BROWSER_COMPLETE', text)
        self.assertNotIn('eval "$(_YOUTUBE_COMPLETE', text)
        self.assertIn("PYTHONWARNINGS=ignore", text)
        self.assertIn("</dev/null", text)
        self.assertIn("*/browser-use/*", text)
        self.assertIn('[[ "$out" == *"complete -"* ]]', text)
        self.assertIn("_fastmarket_load_completion browser bash_source", text)
        self.assertIn("_fastmarket_load_completion youtube bash_source", text)
        self.assertTrue(text.endswith("unset -f _fastmarket_load_completion"))

    def test_zsh_and_fish_scripts_guard_eval(self):
        zsh = "\n".join(_generate_completion_script("zsh", ["youtube"]))
        fish = "\n".join(_generate_completion_script("fish", ["youtube"]))

        self.assertIn("compdef ", zsh)
        self.assertIn("</dev/null", zsh)
        self.assertIn("complete --", fish)
        self.assertIn("</dev/null", fish)
        self.assertNotIn('eval "$(_YOUTUBE_COMPLETE', zsh)
        self.assertNotIn("eval (_YOUTUBE_COMPLETE", fish)

    def test_unsafe_command_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsafe command name"):
            _generate_completion_script("bash", ["youtube; rm -rf /"])

    def test_unknown_shell_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported shell"):
            _generate_completion_script("tcsh", ["youtube"])

    def test_tty_startup_does_not_eval_welcome_text_or_show_warnings(self):
        with tempfile.TemporaryDirectory() as raw:
            self._tty_startup(Path(raw))

    def _tty_startup(self, tmp_path: Path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        tty_marker = tmp_path / "saw-tty"
        launched = tmp_path / "launched"

        browser = bin_dir / "browser"
        browser.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"marker = Path({str(tty_marker)!r})\n"
            f"launched = Path({str(launched)!r})\n"
            "if sys.stdin.isatty():\n"
            "    marker.write_text('tty')\n"
            f"print({QUICKSTART!r})\n"
            "print('FutureWarning: You are using a Python version (3.11.9)', file=sys.stderr)\n"
            "if sys.stdin.isatty():\n"
            "    launched.write_text('should-not-run-inside-python')\n"
        )
        browser.chmod(0o755)

        youtube = bin_dir / "youtube"
        youtube.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "if os.environ.get('_YOUTUBE_COMPLETE') == 'bash_source':\n"
            "    print('_youtube_completion() { :; }')\n"
            "    print('complete -o nosort -F _youtube_completion youtube')\n"
            "else:\n"
            "    print('youtube-ran', file=sys.stderr)\n"
            "    raise SystemExit(1)\n"
        )
        youtube.chmod(0o755)

        script_path = tmp_path / "fast-market.bash"
        script_path.write_text(
            "\n".join(_generate_completion_script("bash", ["browser", "youtube"])) + "\n"
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        env.pop("PYENV_VERSION", None)
        env.pop("VIRTUAL_ENV", None)

        code, output = _bash_on_pty(
            f"source {script_path}\n"
            "echo FASTMARKET_COMPLETIONS_DONE\n"
            "complete -p youtube || true\n"
            "complete -p browser || true\n",
            env,
        )

        self.assertEqual(code, 0, output)
        self.assertIn("FASTMARKET_COMPLETIONS_DONE", output)
        self.assertIn("complete -o nosort -F _youtube_completion youtube", output)
        self.assertNotIn("Welcome", output)
        self.assertNotIn("here-document", output)
        self.assertNotIn("FutureWarning", output)
        self.assertTrue(
            "no completion specification" in output or "pas d'indication" in output,
            output,
        )
        self.assertFalse(tty_marker.exists(), output)
        self.assertFalse(launched.exists(), output)


if __name__ == "__main__":
    unittest.main()


def _bash_on_pty(script: str, env: dict[str, str], timeout: float = 10) -> tuple[int, str]:
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["bash", "--noprofile", "--norc", "-ic", script],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    chunks: list[bytes] = []
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                while True:
                    ready, _, _ = select.select([master], [], [], 0.05)
                    if not ready:
                        break
                    try:
                        data = os.read(master, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    chunks.append(data)
                break
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        else:
            proc.kill()
    finally:
        os.close(master)
    code = proc.wait(timeout=2)
    return code, b"".join(chunks).decode("utf-8", "replace")
