"""Custom Click ParamType classes for shell completion."""

from __future__ import annotations

import click
from click.shell_completion import CompletionItem

from common.core.registry import discover_plugins
from core.config import _social_config_root

_TOOL_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


class BackendParamType(click.ParamType):
    """Tab-completable backend names from discovered plugins."""

    name = "backend"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        try:
            # Use config loaded during _load() to get real manifests
            config: dict = getattr(ctx.obj, "get", lambda k, d: d)({})
            if not config:
                from commands.helpers import load_config

                config = load_config()
        except Exception:
            config = {}

        try:
            manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
            return [
                CompletionItem(name, help=f"Backend: {name}")
                for name in sorted(manifests.keys())
                if incomplete.lower() in name.lower()
            ]
        except Exception:
            return []

    def convert(self, value, param, ctx):
        return value


class ShellType(click.ParamType):
    """Tab-completable shell type for completion scripts."""

    name = "shell"
    SHELLS = {"bash", "zsh", "fish"}

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        return [
            CompletionItem(name, help=f"Generate for {name}")
            for name in sorted(self.SHELLS)
            if incomplete.lower() in name.lower()
        ]

    def convert(self, value, param, ctx):
        return value
