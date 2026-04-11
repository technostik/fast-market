from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandManifest:
    """What a command contributes to the CLI."""
    name: str
    click_command: Any
    api_router: Any | None = None
