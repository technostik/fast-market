from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.models import SearchItem


class SearchPlugin(ABC):
    """A web-search provider.

    Subclasses implement :meth:`search`, returning normalized
    :class:`~core.models.SearchItem` objects (never plugin-specific shapes).
    """

    name: str

    @abstractmethod
    def search(self, query: str, limit: int, **kwargs) -> list[SearchItem]:
        """Return up to `limit` results for `query`.

        `kwargs` carry plugin-injected CLI options (e.g. --hl, --subreddit)
        and shared values (e.g. language). Unknown keys must be ignored.
        """
        raise NotImplementedError


@dataclass
class PluginManifest:
    """Everything a plugin contributes to the system.

    Fields:
        name:            Must match SearchPlugin.name.
        provider_class:  The SearchPlugin subclass (not an instance).
        cli_options:     {command_name: [click.Option, ...]}. Use "*" for all.
        api_router:      Optional FastAPI router.
        frontend_js:     Optional JS snippet.
    """

    name: str
    provider_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None
