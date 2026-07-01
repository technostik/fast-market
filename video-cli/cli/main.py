from __future__ import annotations

import logging
import os
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.registry import discover_commands

main = create_cli_group(
    "video-agent",
    description="Process videos with silence removal, transcription, subtitles, and Modal diagnostics."
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    command_manifests = discover_commands(None, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


# Load .env from repo root and ensure CWD is repo root before any
# Modal imports (Secret.from_dotenv() reads .env from CWD at import time).
# Without this, webux serve spawning the video CLI from a different
# directory would produce an empty Modal Secret → empty GROQ_API_KEY → 401.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env", override=True)
except ImportError:
    pass
os.chdir(str(_REPO_ROOT))

_load()

if __name__ == "__main__":
    main()
