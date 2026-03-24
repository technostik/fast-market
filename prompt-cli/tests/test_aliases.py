from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def clear_aliases_cache():
    """Clear the aliases cache before each test."""
    import common.core.aliases as aliases_module

    aliases_module._aliases_cache = None
    yield
    aliases_module._aliases_cache = None


@pytest.fixture
def temp_aliases_file(tmp_path, monkeypatch):
    """Create a temporary aliases file."""
    config_dir = tmp_path / "config" / "prompt-agent"
    config_dir.mkdir(parents=True)
    aliases_file = config_dir / "aliases.yaml"
    monkeypatch.setattr("common.core.aliases._get_aliases_path", lambda: aliases_file)
    return aliases_file


@pytest.fixture
def runner():
    return CliRunner()


class TestAliasResolution:
    """Tests for core alias resolution functions."""

    def test_load_aliases_empty_file(self, temp_aliases_file):
        """Test loading from empty file."""
        from common.core.aliases import load_aliases

        temp_aliases_file.write_text("", encoding="utf-8")
        aliases = load_aliases(force_reload=True)
        assert aliases == {}

    def test_load_aliases_valid(self, temp_aliases_file):
        """Test loading valid aliases."""
        from common.core.aliases import load_aliases

        data = {
            "aliases": {
                "ls-files": {"command": "ls -la", "description": ""},
                "alert-me": {"command": "message alert", "description": ""},
            }
        }
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        aliases = load_aliases(force_reload=True)
        assert aliases == {
            "ls-files": {"command": "ls -la", "description": ""},
            "alert-me": {"command": "message alert", "description": ""},
        }

    def test_load_aliases_invalid_yaml(self, temp_aliases_file):
        """Test loading invalid YAML."""
        from common.core.aliases import load_aliases

        temp_aliases_file.write_text("invalid: yaml: content:", encoding="utf-8")
        aliases = load_aliases(force_reload=True)
        assert aliases == {}

    def test_load_aliases_missing_file(self, temp_aliases_file, monkeypatch):
        """Test loading from non-existent file."""
        from common.core.aliases import load_aliases

        monkeypatch.setattr(
            "common.core.aliases._get_aliases_path",
            lambda: Path("/nonexistent/path.yaml"),
        )
        aliases = load_aliases(force_reload=True)
        assert aliases == {}

    def test_resolve_alias_simple(self, temp_aliases_file):
        """Test simple alias resolution."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"ls-files": "ls -la"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("ls-files")
        assert resolved == "ls -la"
        assert alias_used == "ls-files"

    def test_resolve_alias_with_args(self, temp_aliases_file):
        """Test alias resolution with arguments."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"alert-me": "message alert"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("alert-me 'server is down'")
        assert resolved == "message alert 'server is down'"
        assert alias_used == "alert-me"

    def test_resolve_alias_no_match(self, temp_aliases_file):
        """Test alias resolution when no alias matches."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"ls-files": "ls -la"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("ls -la")
        assert resolved == "ls -la"
        assert alias_used is None

    def test_resolve_alias_multiple_words(self, temp_aliases_file):
        """Test alias with multiple word command."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"img-gen": "image generate"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("img-gen 'a cat'")
        assert resolved == "image generate 'a cat'"
        assert alias_used == "img-gen"

    def test_resolve_alias_nested(self, temp_aliases_file):
        """Test nested alias resolution."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"a": "b", "b": "c"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("a arg1")
        assert resolved == "c arg1"
        assert alias_used == "a"

    def test_resolve_alias_max_depth(self, temp_aliases_file):
        """Test alias resolution with max depth (circular detection)."""
        from common.core.aliases import resolve_alias

        data = {"aliases": {"a": "b", "b": "c", "c": "d", "d": "e", "e": "f", "f": "g"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        resolved, alias_used = resolve_alias("a arg1")
        assert alias_used == "a"

    def test_get_all_aliases(self, temp_aliases_file):
        """Test get_all_aliases function."""
        from common.core.aliases import get_all_aliases

        data = {
            "aliases": {
                "alias1": {"command": "cmd1", "description": ""},
                "alias2": {"command": "cmd2", "description": ""},
            }
        }
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        aliases = get_all_aliases()
        assert aliases == {
            "alias1": {"command": "cmd1", "description": ""},
            "alias2": {"command": "cmd2", "description": ""},
        }

    def test_get_reverse_aliases(self, temp_aliases_file):
        """Test get_reverse_aliases function."""
        from common.core.aliases import get_reverse_aliases

        data = {"aliases": {"alias1": "cmd1", "alias2": "cmd1", "alias3": "cmd2"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        reverse = get_reverse_aliases()
        assert reverse == {"cmd1": ["alias1", "alias2"], "cmd2": ["alias3"]}

    def test_get_aliases_for_command(self, temp_aliases_file):
        """Test get_aliases_for_command function."""
        from common.core.aliases import get_aliases_for_command

        data = {"aliases": {"alias1": "cmd1", "alias2": "cmd1"}}
        temp_aliases_file.write_text(yaml.dump(data), encoding="utf-8")

        aliases = get_aliases_for_command("cmd1")
        assert aliases == ["alias1", "alias2"]

    def test_create_alias(self, temp_aliases_file):
        """Test creating a new alias."""
        from common.core.aliases import create_or_update_alias, get_all_aliases

        is_new = create_or_update_alias("new-alias", "new command")
        assert is_new is True
        assert get_all_aliases()["new-alias"] == {
            "command": "new command",
            "description": "",
        }

    def test_update_alias(self, temp_aliases_file):
        """Test updating an existing alias."""
        from common.core.aliases import create_or_update_alias, get_all_aliases

        create_or_update_alias("existing", "old command")
        is_new = create_or_update_alias("existing", "new command")

        assert is_new is False
        assert get_all_aliases()["existing"] == {
            "command": "new command",
            "description": "",
        }

    def test_remove_alias(self, temp_aliases_file):
        """Test removing an alias."""
        from common.core.aliases import (
            create_or_update_alias,
            get_all_aliases,
            remove_alias,
        )

        create_or_update_alias("to-remove", "some command")
        assert "to-remove" in get_all_aliases()

        removed = remove_alias("to-remove")
        assert removed is True
        assert "to-remove" not in get_all_aliases()

    def test_remove_nonexistent_alias(self, temp_aliases_file):
        """Test removing a non-existent alias."""
        from common.core.aliases import remove_alias

        removed = remove_alias("nonexistent")
        assert removed is False

    def test_merge_aliases_from_file(self, temp_aliases_file, tmp_path):
        """Test merging aliases from a file."""
        from common.core.aliases import (
            create_or_update_alias,
            get_all_aliases,
            merge_aliases_from_file,
        )

        create_or_update_alias("existing", "old command")

        import_file = tmp_path / "import.yaml"
        import_data = {
            "aliases": {"new1": {"command": "cmd1"}, "new2": {"command": "cmd2"}}
        }
        import_file.write_text(yaml.dump(import_data), encoding="utf-8")

        count = merge_aliases_from_file(import_file)
        assert count == 2

        aliases = get_all_aliases()
        assert aliases["existing"] == {"command": "old command", "description": ""}
        assert aliases["new1"] == {"command": "cmd1", "description": ""}
        assert aliases["new2"] == {"command": "cmd2", "description": ""}

    def test_export_aliases(self, temp_aliases_file):
        """Test exporting aliases."""
        from common.core.aliases import create_or_update_alias, export_aliases

        create_or_update_alias("alias1", "cmd1")
        create_or_update_alias("alias2", "cmd2")

        exported = export_aliases()
        parsed = yaml.safe_load(exported)
        assert parsed["aliases"] == {
            "alias1": {"command": "cmd1", "description": ""},
            "alias2": {"command": "cmd2", "description": ""},
        }


class TestAliasCommand:
    """Tests for the alias CLI command."""

    def test_alias_list_empty(self, runner, temp_aliases_file, monkeypatch):
        """Test listing aliases when none exist."""
        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, [])
        assert "No aliases defined" in result.output

    def test_alias_list(self, runner, temp_aliases_file, monkeypatch):
        """Test listing aliases."""
        from common.core.aliases import create_or_update_alias

        create_or_update_alias("alias1", "cmd1")
        create_or_update_alias("alias2", "cmd2")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, [])

        assert "alias1: cmd1" in result.output
        assert "alias2: cmd2" in result.output

    def test_alias_create(self, runner, temp_aliases_file, monkeypatch):
        """Test creating an alias via CLI."""
        from commands.alias.register import register
        from common.core.aliases import get_all_aliases

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["new-alias", "new command"])

        assert result.exit_code == 0
        assert "✓ Alias created" in result.output
        assert get_all_aliases()["new-alias"] == {
            "command": "new command",
            "description": "",
        }

    def test_alias_show(self, runner, temp_aliases_file, monkeypatch):
        """Test showing a specific alias."""
        from common.core.aliases import create_or_update_alias

        create_or_update_alias("show-me", "shown command")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["show-me"])

        assert result.exit_code == 0
        assert "show-me: shown command" in result.output

    def test_alias_show_nonexistent(self, runner, temp_aliases_file, monkeypatch):
        """Test showing a non-existent alias."""
        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["nonexistent"])

        assert result.exit_code == 1
        assert "Error: Alias not found" in result.output

    def test_alias_remove(self, runner, temp_aliases_file, monkeypatch):
        """Test removing an alias."""
        from common.core.aliases import create_or_update_alias, get_all_aliases

        create_or_update_alias("to-remove", "some command")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["to-remove", "--remove"])

        assert result.exit_code == 0
        assert "✓ Alias removed" in result.output
        assert "to-remove" not in get_all_aliases()

    def test_alias_remove_nonexistent(self, runner, temp_aliases_file, monkeypatch):
        """Test removing a non-existent alias."""
        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["nonexistent", "--remove"])

        assert result.exit_code == 1
        assert "Error: Alias not found" in result.output

    def test_alias_config_path(self, runner, temp_aliases_file, monkeypatch):
        """Test showing config path."""
        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["--config-path"])

        assert result.exit_code == 0
        assert str(temp_aliases_file) in result.output

    def test_alias_export(self, runner, temp_aliases_file, monkeypatch):
        """Test exporting aliases."""
        from common.core.aliases import create_or_update_alias

        create_or_update_alias("alias1", "cmd1")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["--export"])

        assert result.exit_code == 0
        assert "aliases:" in result.output
        assert "alias1:" in result.output
        assert "command: cmd1" in result.output

    def test_alias_export_json(self, runner, temp_aliases_file, monkeypatch):
        """Test exporting aliases as JSON."""
        import json
        from common.core.aliases import create_or_update_alias

        create_or_update_alias("alias1", "cmd1")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["--export", "--format", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["aliases"] == {"alias1": {"command": "cmd1", "description": ""}}

    def test_alias_import(self, runner, temp_aliases_file, tmp_path, monkeypatch):
        """Test importing aliases from file."""
        import_file = tmp_path / "import.yaml"
        import_data = {"aliases": {"imported": "imported command"}}
        import_file.write_text(yaml.dump(import_data), encoding="utf-8")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["--file", str(import_file)])

        assert result.exit_code == 0
        assert "✓ Loaded 1 aliases" in result.output

    def test_alias_list_flag(self, runner, temp_aliases_file, monkeypatch):
        """Test --list flag."""
        from common.core.aliases import create_or_update_alias

        create_or_update_alias("list-alias", "list command")

        from commands.alias.register import register

        manifest = register({})
        result = runner.invoke(manifest.click_command, ["--list"])

        assert result.exit_code == 0
        assert "list-alias: list command" in result.output


class TestExecutorWithAliases:
    """Tests for executor integration with aliases."""

    def test_executor_resolves_alias(self, temp_aliases_file, monkeypatch):
        """Test that executor resolves aliases."""
        from common.core.aliases import create_or_update_alias
        from commands.task.executor import resolve_and_execute_command

        create_or_update_alias("test-alias", "echo test output")

        from pathlib import Path

        result = resolve_and_execute_command(
            "test-alias",
            Path("/tmp"),
            {"echo"},
            60,
        )

        assert result.exit_code == 0
        assert result.stdout.strip() == "test output"
        assert result.resolved_from_alias == "test-alias"
        assert result.original_command == "test-alias"

    def test_executor_validates_resolved_command(self, temp_aliases_file, monkeypatch):
        """Test that executor validates the resolved command."""
        from common.core.aliases import create_or_update_alias
        from commands.task.executor import resolve_and_execute_command

        create_or_update_alias("bad-alias", "not-allowed-cmd arg")

        from pathlib import Path

        result = resolve_and_execute_command(
            "bad-alias",
            Path("/tmp"),
            {"echo"},
            60,
        )

        assert result.exit_code == 126
        assert "not in whitelist" in result.stderr.lower()
        assert "from alias 'bad-alias'" in result.stderr

    def test_execute_dry_run_with_alias(self, temp_aliases_file, monkeypatch):
        """Test dry-run shows alias resolution."""
        from common.core.aliases import create_or_update_alias
        from commands.task.executor import execute_dry_run

        create_or_update_alias("dry-alias", "echo dry")

        from pathlib import Path

        result = execute_dry_run("dry-alias", Path("/tmp"), {"echo"})

        assert result["resolved_command"] == "echo dry"
        assert result["alias_used"] == "dry-alias"
        assert result["would_execute"] is True

    def test_execute_dry_run_with_alias_not_allowed(
        self, temp_aliases_file, monkeypatch
    ):
        """Test dry-run shows alias resolution failure."""
        from common.core.aliases import create_or_update_alias
        from commands.task.executor import execute_dry_run

        create_or_update_alias("bad-dry-alias", "not-allowed arg")

        from pathlib import Path

        result = execute_dry_run("bad-dry-alias", Path("/tmp"), {"echo"})

        assert result["resolved_command"] == "not-allowed arg"
        assert result["alias_used"] == "bad-dry-alias"
        assert result["would_execute"] is False
        assert "not in whitelist" in result["reason"].lower()
