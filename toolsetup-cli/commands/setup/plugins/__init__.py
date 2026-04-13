from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


class ConfigPlugin(ABC):
    """Base class for toolsetup subconfig plugins."""

    name: ClassVar[str]
    display_name: ClassVar[str]

    @abstractmethod
    def config_path(self) -> Path:
        """Return the absolute path to the config file."""
        ...

    @abstractmethod
    def load(self) -> dict:
        """Load and return the config dict. Returns {} if file missing."""
        ...

    @abstractmethod
    def save(self, config: dict) -> None:
        """Save the config dict to the config file."""
        ...

    @abstractmethod
    def default_config(self) -> dict:
        """Return the default config dict for reset operations."""
        ...

    def ensure_exists(self) -> None:
        """Create the config file with defaults if it does not exist."""
        path = self.config_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self.save(self.default_config())

    def __repr__(self) -> str:
        return f"<ConfigPlugin name={self.name!r} display={self.display_name!r}>"


# ─── Plugin Registry ─────────────────────────────────────────────────────────

_plugins: dict[str, ConfigPlugin] = {}


def register_plugin(plugin: ConfigPlugin) -> None:
    """Register a subconfig plugin."""
    _plugins[plugin.name] = plugin


def get_plugin(name: str) -> ConfigPlugin:
    """Get a plugin by name. Raises KeyError if not found."""
    if name not in _plugins:
        available = ", ".join(sorted(_plugins))
        raise KeyError(f"Unknown subconfig plugin: {name!r}. Available: {available}")
    return _plugins[name]


def all_plugins() -> dict[str, ConfigPlugin]:
    """Return all registered plugins."""
    return dict(_plugins)
