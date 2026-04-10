from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginManifest:
    """Everything a plugin contributes to the system."""

    name: str
    source_plugin_class: type | None = None
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
    frontend_js: str | None = None
    config_template: str | None = None
    """Default commented config.yaml template provided by the plugin."""


class SocialPlugin(ABC):
    """Abstract base class for social backend plugins."""

    name: str

    @abstractmethod
    def post(self, text: str, media: list[str] | None = None) -> dict:
        """Post a message. Returns dict with result info.

        Args:
            text: The text content to post.
            media: Optional list of file paths to attach.
                   If the backend doesn't support media, it should warn.
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, max_results: int = 10, language: str = "en") -> list[dict]:
        """Search posts on this backend.

        Args:
            query: Search keywords.
            max_results: Maximum number of results.
            language: Language filter.
        Returns:
            List of post dicts with keys like: id, text, author, url, created_at.
        """
        raise NotImplementedError
