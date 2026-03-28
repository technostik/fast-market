from __future__ import annotations

import logging
import os
from pathlib import Path

import click

from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config
from common.core.registry import discover_commands, discover_plugins

requires_common_config("skill", [])

main = create_cli_group("skill")
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_tool_config("skill")
    plugin_manifests = {}
    if (_TOOL_ROOT / "plugins").exists():
        plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)

    @main.command("completion")
    @click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), required=False)
    def completion_cmd(shell):
        """Print shell completion activation instructions."""
        target_shell = shell
        if not target_shell:
            env_shell = os.environ.get("SHELL", "")
            if env_shell.endswith("bash"):
                target_shell = "bash"
            elif env_shell.endswith("zsh"):
                target_shell = "zsh"
            elif env_shell.endswith("fish"):
                target_shell = "fish"

        snippets = {
            "bash": '# Add to ~/.bashrc:\neval "$(_SKILL_COMPLETE=bash_source skill)"',
            "zsh": '# Add to ~/.zshrc:\neval "$(_SKILL_COMPLETE=zsh_source skill)"',
            "fish": "# Add to ~/.config/fish/completions/skill.fish:\n_SKILL_COMPLETE=fish_source skill | source",
        }

        if target_shell:
            click.echo(snippets[target_shell])
            return

        click.echo(snippets["bash"])
        click.echo()
        click.echo(snippets["zsh"])
        click.echo()
        click.echo(snippets["fish"])


_load()

if __name__ == "__main__":
    main()
