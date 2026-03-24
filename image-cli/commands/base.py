from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandManifest:
    """
    Everything a command contributes to the system.

    Fields:
        name:          CLI name (e.g. "generate", "setup").
        click_command: A fully-decorated @click.command (params may be extended
                      after creation by the registry injecting plugin options).
        api_router:    Optional FastAPI APIRouter with endpoints for this command.
    """

    name: str
    click_command: Any
    api_router: Any | None = None
