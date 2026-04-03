from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner


TESTS_DIR = Path(__file__).parent
FIXTURE_CONFIG = TESTS_DIR / "fixtures" / "config"


@pytest.fixture
def tool_name():
    return "test-tool"


@pytest.fixture
def defaults():
    return {
        "system": "You are a helpful assistant.",
        "summarize": "Summarize: {content}",
    }


@pytest.fixture(autouse=True)
def cleanup_prompts(tool_name):
    """Clean up prompts before each test."""
    from common.core.paths import get_tool_config_path

    prompts_dir = get_tool_config_path(tool_name).parent / "prompts"
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.yaml"):
            f.unlink()
    yield
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.yaml"):
            f.unlink()


@pytest.fixture
def manager(tool_name, defaults):
    from common.prompt import PromptManager

    return PromptManager(tool_name, defaults)


@pytest.fixture
def prompts_dir(tool_name):
    from common.core.paths import get_tool_config_path

    return get_tool_config_path(tool_name).parent / "prompts"


def test_prompt_manager_create(manager, defaults):
    assert manager.create("system", "Custom system prompt")
    content = manager.get("system")
    assert content == "Custom system prompt"

    assert manager.get("summarize") == defaults["summarize"]


def test_prompt_manager_create_existing_fails(manager):
    manager.create("system", "First version")
    result = manager.create("system", "Second version")
    assert result is False


def test_prompt_manager_delete(manager):
    manager.create("system", "Custom")
    assert manager.delete("system") is True
    assert manager.get("system") is not None


def test_prompt_manager_delete_nonexistent(manager):
    assert manager.delete("nonexistent") is False


def test_prompt_manager_rename(manager):
    manager.create("system", "Custom")
    assert manager.rename("system", "system_new") is True
    assert manager.get("system_new") == "Custom"
    assert manager.get("system") == manager.defaults["system"]


def test_prompt_manager_rename_nonexistent(manager):
    assert manager.rename("nonexistent", "new_name") is False


def test_prompt_manager_rename_existing_target(manager):
    manager.create("system", "Custom 1")
    manager.create("summarize", "Custom 2")
    assert manager.rename("system", "summarize") is False


def test_prompt_manager_get(manager):
    assert manager.get("system") == manager.defaults["system"]
    manager.create("system", "Custom")
    assert manager.get("system") == "Custom"


def test_prompt_manager_get_nonexistent(manager):
    assert manager.get("nonexistent") is None


def test_prompt_manager_list(manager):
    result = manager.list()
    ids = [p[0] for p in result]
    assert "system" in ids
    assert "summarize" in ids

    manager.create("system", "Custom")
    result = manager.list()
    for pid, is_override in result:
        if pid == "system":
            assert is_override is True


def test_prompt_manager_set(manager):
    manager.set("system", "New content")
    assert manager.get("system") == "New content"


def test_prompt_manager_show(manager):
    manager.create("system", "Custom system")
    result = manager.show()
    assert "system" in result
    content, is_override = result["system"]
    assert content == "Custom system"
    assert is_override is True


def test_prompt_manager_path(manager, prompts_dir):
    assert manager.path() == prompts_dir

    manager.create("system", "Custom")
    assert manager.path("system") == prompts_dir / "system.yaml"


def test_prompt_manager_reset_one(manager):
    manager.create("system", "Custom")
    count = manager.reset("system")
    assert count == 1
    assert manager.get("system") == manager.defaults["system"]


def test_prompt_manager_reset_all(manager):
    manager.create("system", "Custom")
    manager.create("summarize", "Custom summarize")

    custom_prompt_id = "custom-prompt"
    manager.set(custom_prompt_id, "Custom non-default")

    count = manager.reset()
    assert count == 3

    assert manager.get("system") == manager.defaults["system"]
    assert manager.get("summarize") == manager.defaults["summarize"]
    assert manager.get(custom_prompt_id) is None


def test_prompt_manager_custom_prompts(manager):
    manager.set("custom-id", "Custom prompt content")
    assert manager.get("custom-id") == "Custom prompt content"

    result = manager.list()
    ids = [p[0] for p in result]
    assert "custom-id" in ids


class TestPromptCLI:
    @pytest.fixture
    def cli_runner(self):
        return CliRunner()

    @pytest.fixture
    def click_group(self):
        import click

        @click.group()
        def cli():
            pass

        return cli

    def test_register_creates_prompt_group(self, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        assert "prompt" in click_group.commands
        prompt_cmd = click_group.commands["prompt"]
        assert isinstance(prompt_cmd, click.Group)

    def test_prompt_create_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        result = cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )
        assert result.exit_code == 0
        assert "Created prompt: system" in result.output

    def test_prompt_get_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "get", "system"])
        assert result.exit_code == 0
        assert "Hello" in result.output

    def test_prompt_get_default(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        result = cli_runner.invoke(click_group, ["prompt", "get", "summarize"])
        assert result.exit_code == 0
        assert defaults["summarize"] in result.output

    def test_prompt_list_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "list"])
        assert result.exit_code == 0
        assert "system" in result.output
        assert "summarize" in result.output

    def test_prompt_list_shows_override_marker(
        self, cli_runner, click_group, tool_name, defaults
    ):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "list"])
        assert "system *" in result.output

    def test_prompt_set_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        result = cli_runner.invoke(
            click_group, ["prompt", "set", "system", "--content", "Updated"]
        )
        assert result.exit_code == 0
        assert "Updated prompt: system" in result.output

        result = cli_runner.invoke(click_group, ["prompt", "get", "system"])
        assert "Updated" in result.output

    def test_prompt_delete_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(
            click_group, ["prompt", "delete", "system", "--force"]
        )
        assert result.exit_code == 0
        assert "Deleted prompt: system" in result.output

    def test_prompt_reset_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "reset", "system"])
        assert result.exit_code == 0

        result = cli_runner.invoke(click_group, ["prompt", "get", "system"])
        assert defaults["system"] in result.output

    def test_prompt_reset_all(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )
        cli_runner.invoke(
            click_group, ["prompt", "create", "summarize", "--content", "World"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "reset"])
        assert result.exit_code == 0
        assert "Reset" in result.output

    def test_prompt_path_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands
        from common.core.paths import get_tool_config_path

        register_commands(click_group, tool_name, defaults)

        expected = get_tool_config_path(tool_name).parent / "prompts"

        result = cli_runner.invoke(click_group, ["prompt", "path"])
        assert result.exit_code == 0
        assert str(expected) in result.output

    def test_prompt_show_command(self, cli_runner, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        cli_runner.invoke(
            click_group, ["prompt", "create", "system", "--content", "Hello"]
        )

        result = cli_runner.invoke(click_group, ["prompt", "show"])
        assert result.exit_code == 0
        assert "system" in result.output
        assert "Hello" in result.output


class TestPromptAutocomplete:
    @pytest.fixture
    def click_group(self):
        import click

        @click.group()
        def cli():
            pass

        return cli

    @pytest.fixture
    def cli_runner(self):
        return CliRunner()

    def test_autocomplete_includes_defaults(self, click_group, tool_name, defaults):
        from common.prompt import register_commands

        register_commands(click_group, tool_name, defaults)

        from common.prompt import PromptManager, PromptIdType

        manager = PromptManager(tool_name, defaults)
        param_type = PromptIdType(manager)

        class MockParam:
            name = "prompt_id"

        completions = param_type.shell_complete(None, MockParam(), "")

        ids = [c.value for c in completions]
        assert "system" in ids
        assert "summarize" in ids
