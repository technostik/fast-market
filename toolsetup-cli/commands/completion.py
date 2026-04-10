from __future__ import annotations

import click
from click.shell_completion import CompletionItem
from pathlib import Path

from common.core.config import load_llm_config


class ProviderParamType(click.ParamType):
    name = "provider"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        config = load_llm_config()
        providers = config.get("providers", {})
        return [
            CompletionItem(name)
            for name in sorted(providers.keys())
            if incomplete.lower() in name.lower()
        ]

    def convert(self, value, param, ctx):
        return value


class AvailableProviderParamType(click.ParamType):
    name = "available_provider"

    AVAILABLE = {
        "anthropic",
        "openai",
        "openai-compatible",
        "ollama",
    }

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        return [
            CompletionItem(name)
            for name in sorted(self.AVAILABLE)
            if incomplete.lower() in name.lower()
        ]

    def convert(self, value, param, ctx):
        return value


class ShellType(click.ParamType):
    name = "shell"

    SHELLS = {"bash", "zsh", "fish"}

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        return [
            CompletionItem(name)
            for name in sorted(self.SHELLS)
            if incomplete.lower() in name.lower()
        ]

    def convert(self, value, param, ctx):
        return value


class PathParamType(click.ParamType):
    name = "path"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        """Complete directory paths for workdir option."""
        try:
            path = Path(incomplete) if incomplete else Path(".")
            
            if path.is_absolute() or (incomplete and incomplete.startswith("~")):
                base_path = path.expanduser()
            else:
                base_path = Path.cwd() / path
            
            parent = base_path.parent if base_path.name else base_path
            
            if not parent.exists():
                return []
            
            items = []
            for item in parent.iterdir():
                if item.name.startswith(base_path.name if base_path.name else ""):
                    if item.is_dir():
                        items.append(CompletionItem(str(item) + "/", help="Directory"))
                    elif item.is_file():
                        items.append(CompletionItem(str(item), help="File"))
            
            return items[:50]  # Limit to 50 items
        except (PermissionError, OSError):
            return []

    def convert(self, value, param, ctx):
        return value
