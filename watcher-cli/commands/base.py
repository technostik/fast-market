from dataclasses import dataclass
from typing import Any
@dataclass(slots=True)
class CommandManifest:
    name: str
    click_command: Any
