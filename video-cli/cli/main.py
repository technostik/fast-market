from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.registry import discover_commands

main = create_cli_group(
    "video-agent",
    description="Process videos with silence removal, transcription, subtitles, and Modal diagnostics."
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    command_manifests = discover_commands(None, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()

if __name__ == "__main__":
    main()
