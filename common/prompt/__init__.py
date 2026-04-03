from __future__ import annotations

import os
import shutil
from pathlib import Path

import click
import yaml
from click.shell_completion import CompletionItem

from common.core.paths import get_tool_config_path
from common.core.yaml_utils import dump_yaml


_managers: dict[str, "PromptManager"] = {}


def _get_prompts_dir(tool_name: str) -> Path:
    """Get prompts directory for a tool, creating it if needed."""
    prompts_dir = get_tool_config_path(tool_name).parent / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def get_prompt_manager(tool_name: str, defaults: dict[str, str]) -> "PromptManager":
    """Get a PromptManager instance for a tool (cached)."""
    if tool_name not in _managers:
        _managers[tool_name] = PromptManager(tool_name, defaults)
    return _managers[tool_name]


def get_cached_manager(tool_name: str) -> "PromptManager | None":
    """Get a cached PromptManager if one exists."""
    return _managers.get(tool_name)


class PromptManager:
    """Manages prompts for a specific tool."""

    def __init__(self, tool_name: str, defaults: dict[str, str]):
        self.tool_name = tool_name
        self.defaults = defaults
        self.prompts_dir = _get_prompts_dir(tool_name)

    def _get_prompt_path(self, prompt_id: str) -> Path:
        return self.prompts_dir / f"{prompt_id}.yaml"

    def create(self, prompt_id: str, content: str) -> bool:
        """Create a new prompt. Returns False if already exists."""
        if (
            prompt_id in self.defaults
            and self.get(prompt_id) == self.defaults[prompt_id]
        ):
            pass
        elif self._get_prompt_path(prompt_id).exists():
            return False

        path = self._get_prompt_path(prompt_id)
        data = {"id": prompt_id, "content": content}
        path.write_text(dump_yaml(data), encoding="utf-8")
        return True

    def delete(self, prompt_id: str) -> bool:
        """Delete a prompt. Returns False if not found."""
        path = self._get_prompt_path(prompt_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def rename(self, old_id: str, new_id: str) -> bool:
        """Rename a prompt. Returns False if old doesn't exist or new exists."""
        old_path = self._get_prompt_path(old_id)
        new_path = self._get_prompt_path(new_id)

        if not old_path.exists():
            return False
        if new_path.exists():
            return False

        data = yaml.safe_load(old_path.read_text(encoding="utf-8")) or {}
        data["id"] = new_id
        new_path.write_text(dump_yaml(data), encoding="utf-8")
        old_path.unlink()
        return True

    def get(self, prompt_id: str) -> str | None:
        """Get prompt content. Returns None if not found or not overridden."""
        path = self._get_prompt_path(prompt_id)
        if not path.exists():
            return self.defaults.get(prompt_id)

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("content", self.defaults.get(prompt_id))

    def list(self) -> list[tuple[str, bool]]:
        """List all prompts: (prompt_id, is_overridden)."""
        result = []

        for prompt_id in self.defaults:
            path = self._get_prompt_path(prompt_id)
            is_overridden = path.exists()
            result.append((prompt_id, is_overridden))

        for path in self.prompts_dir.glob("*.yaml"):
            prompt_id = path.stem
            if prompt_id not in self.defaults:
                result.append((prompt_id, True))

        return sorted(result, key=lambda x: x[0])

    def set(self, prompt_id: str, content: str) -> bool:
        """Set prompt content. Creates if doesn't exist."""
        path = self._get_prompt_path(prompt_id)
        data = {"id": prompt_id, "content": content}
        path.write_text(dump_yaml(data), encoding="utf-8")
        return True

    def edit(self, prompt_id: str) -> bool:
        """Edit prompt in editor. Creates if doesn't exist. Returns False on cancel."""
        from common.cli.helpers import open_editor

        path = self._get_prompt_path(prompt_id)

        if not path.exists():
            default_content = self.defaults.get(prompt_id, "")
            path.write_text(
                dump_yaml({"id": prompt_id, "content": default_content}),
                encoding="utf-8",
            )

        open_editor(path)

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not data.get("content"):
            path.unlink()
            return False
        return True

    def show(self) -> dict[str, tuple[str, bool]]:
        """Show all prompts with content: {id: (content, is_overridden)}."""
        result = {}
        for prompt_id, is_overridden in self.list():
            content = self.get(prompt_id)
            if content:
                result[prompt_id] = (content, is_overridden)
        return result

    def path(self, prompt_id: str | None = None) -> Path | None:
        """Get prompts directory path, or specific prompt path if ID given."""
        if prompt_id:
            return self._get_prompt_path(prompt_id)
        return self.prompts_dir

    def reset(self, prompt_id: str | None = None) -> int:
        """Reset one prompt or ALL to defaults. Returns count of reset prompts."""
        count = 0
        if prompt_id:
            path = self._get_prompt_path(prompt_id)
            if path.exists():
                path.unlink()
                count = 1
        else:
            for prompt_id in self.defaults:
                path = self._get_prompt_path(prompt_id)
                if path.exists():
                    path.unlink()
                    count += 1
            for path in self.prompts_dir.glob("*.yaml"):
                prompt_id = path.stem
                if prompt_id not in self.defaults:
                    path.unlink()
                    count += 1
        return count


class PromptIdType(click.ParamType):
    """Click type for prompt ID with autocomplete."""

    name = "PROMPT_ID"

    def __init__(self, manager: PromptManager):
        self.manager = manager

    def shell_complete(self, ctx, param, incomplete):
        try:
            prompts = self.manager.list()
        except Exception:
            return []

        return [
            CompletionItem(prompt_id, help="overridden" if is_override else "")
            for prompt_id, is_override in prompts
            if prompt_id.startswith(incomplete)
        ]

    def convert(self, value, param, ctx):
        return value


def register_commands(
    click_group: click.Group,
    tool_name: str,
    defaults: dict[str, str],
) -> None:
    """Register prompt subcommands to a Click group."""

    manager = PromptManager(tool_name, defaults)

    @click_group.group("prompt")
    def prompt_group():
        """Manage prompts for this tool."""
        pass

    @prompt_group.command("create")
    @click.argument("prompt_id")
    @click.option("--content", "-c", required=True, help="Prompt content")
    def create_cmd(prompt_id, content):
        """Create a new prompt."""
        if manager.create(prompt_id, content):
            click.echo(f"Created prompt: {prompt_id}")
        else:
            click.echo(f"Error: Prompt '{prompt_id}' already exists", err=True)
            raise click.Abort()

    @prompt_group.command("delete")
    @click.argument("prompt_id", type=PromptIdType(manager))
    @click.option("--force", "-f", is_flag=True, help="Skip confirmation")
    def delete_cmd(prompt_id, force):
        """Delete a prompt."""
        if not force:
            click.confirm(f"Delete prompt '{prompt_id}'?", abort=True)

        if manager.delete(prompt_id):
            click.echo(f"Deleted prompt: {prompt_id}")
        else:
            click.echo(f"Error: Prompt '{prompt_id}' not found", err=True)
            raise click.Abort()

    @prompt_group.command("rename")
    @click.argument("old_id", type=PromptIdType(manager))
    @click.argument("new_id")
    def rename_cmd(old_id, new_id):
        """Rename a prompt."""
        if manager.rename(old_id, new_id):
            click.echo(f"Renamed '{old_id}' to '{new_id}'")
        else:
            click.echo(f"Error: Cannot rename '{old_id}'", err=True)
            raise click.Abort()

    @prompt_group.command("get")
    @click.argument("prompt_id", type=PromptIdType(manager))
    def get_cmd(prompt_id):
        """Get prompt content."""
        content = manager.get(prompt_id)
        if content is None:
            click.echo(f"Error: Prompt '{prompt_id}' not found", err=True)
            raise click.Abort()
        click.echo(content)

    @prompt_group.command("list")
    def list_cmd():
        """List all prompt IDs."""
        prompts = manager.list()
        for prompt_id, is_overridden in prompts:
            marker = " *" if is_overridden else ""
            click.echo(f"{prompt_id}{marker}")

    @prompt_group.command("set")
    @click.argument("prompt_id", type=PromptIdType(manager))
    @click.option("--content", "-c", required=True, help="Prompt content")
    def set_cmd(prompt_id, content):
        """Set prompt content."""
        manager.set(prompt_id, content)
        click.echo(f"Updated prompt: {prompt_id}")

    @prompt_group.command("edit")
    @click.argument("prompt_id", type=PromptIdType(manager))
    def edit_cmd(prompt_id):
        """Edit prompt in editor."""
        manager.edit(prompt_id)
        click.echo(f"Edited prompt: {prompt_id}")

    @prompt_group.command("show")
    def show_cmd():
        """Show all prompts with content."""
        prompts = manager.show()
        for prompt_id, (content, is_overridden) in prompts.items():
            marker = " *" if is_overridden else ""
            click.echo(f"--- {prompt_id}{marker} ---")
            click.echo(content)
            click.echo("")

    @prompt_group.command("path")
    @click.argument("prompt_id", required=False, type=PromptIdType(manager))
    def path_cmd(prompt_id):
        """Show prompts path or specific prompt path."""
        p = manager.path(prompt_id)
        click.echo(p)

    @prompt_group.command("reset")
    @click.argument("prompt_id", required=False, type=PromptIdType(manager))
    def reset_cmd(prompt_id):
        """Reset one or all prompts to defaults."""
        count = manager.reset(prompt_id)
        if count > 0:
            click.echo(f"Reset {count} prompt(s)")
        else:
            click.echo("No prompts to reset")
