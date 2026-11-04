from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class WebuxPluginManifest:
    """Everything a package contributes to the webux hub."""

    name: str
    tab_label: str
    tab_icon: str
    frontend_html: str
    api_router: Any | None = None
    order: int = 100
    lazy: bool = True
    #: Toolbar group for the grouped-dropdown nav (e.g. "Publish").
    #: Empty = grouped by the hub's built-in mapping, else "More".
    group: str = ""
    #: Cheap, side-effect-free probe returning True while the plugin has a
    #: long-running operation. The hub aggregates these into
    #: ``GET /api/system/busy`` so the toolbar can lock profile switching.
    busy_check: Callable[[], bool] | None = None
