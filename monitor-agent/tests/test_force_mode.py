from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from core.models import Source, Rule, ItemMetadata


class TestForceMode:
    """Tests for --force mode functionality."""

    def test_force_mode_flag_recognized(self):
        """Test that --force flag is recognized by the CLI."""
        from cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_limit_flag_recognized(self):
        """Test that --limit flag is recognized by the CLI."""
        from cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output

    def test_run_command_force_mode_with_mock(self, tmp_path):
        """Test run command with --force flag using mocks."""
        from core.storage import MonitorStorage
        from commands.run.register import register

        db_path = tmp_path / "test.db"
        storage = MonitorStorage(db_path)

        source = Source(
            id="test-src",
            plugin="youtube",
            identifier="UC123456789",
            description="Test Channel",
            last_fetched_at=None,
            created_at=datetime.now(),
        )
        storage.add_source(source)

        rule = Rule(
            id="test-rule",
            name="Test Rule",
            conditions={"all": [{"field": "source_plugin", "operator": "==", "value": "youtube"}]},
            action_ids=[],
            created_at=datetime.now(),
        )
        storage.add_rule(rule)

        items = [
            ItemMetadata(
                id="item-1",
                title="Video 1",
                url="https://youtube.com/watch?v=1",
                published_at=datetime.now(timezone.utc),
                content_type="video",
                source_plugin="youtube",
                source_identifier="UC123456789",
                extra={},
            ),
        ]

        called_args = {}

        async def mock_fetch_new_items(
            last_item_id=None, limit=50, last_fetched_at=None, force=False
        ):
            called_args["last_item_id"] = last_item_id
            called_args["limit"] = limit
            called_args["last_fetched_at"] = last_fetched_at
            called_args["force"] = force
            return items

        mock_plugin_instance = MagicMock()
        mock_plugin_instance.fetch_new_items.side_effect = mock_fetch_new_items
        mock_plugin_instance.name = "youtube"

        mock_manifest = MagicMock()
        mock_manifest.source_plugin_class.return_value = mock_plugin_instance

        manifest = register({"youtube": mock_manifest})
        cmd = manifest.click_command

        def mock_get_storage():
            return storage

        with patch("commands.run.register.get_storage", mock_get_storage):
            runner = CliRunner()
            result = runner.invoke(cmd, ["--force", "--limit", "10", "--format", "json"])

            assert called_args.get("last_item_id") is None
            assert called_args.get("limit") == 10
            assert called_args.get("last_fetched_at") is None
            assert '"mode": "force"' in result.output

    def test_run_command_normal_mode(self, tmp_path):
        """Test run command in normal mode (no --force)."""
        from core.storage import MonitorStorage
        from commands.run.register import register

        db_path = tmp_path / "test.db"
        storage = MonitorStorage(db_path)

        last_fetch = datetime.now(timezone.utc)
        source = Source(
            id="test-src-normal",
            plugin="youtube",
            identifier="UC123456789",
            description="Test Channel",
            last_fetched_at=last_fetch,
            created_at=datetime.now(),
        )
        storage.add_source(source)

        rule = Rule(
            id="test-rule-normal",
            name="Test Rule",
            conditions={"all": [{"field": "source_plugin", "operator": "==", "value": "youtube"}]},
            action_ids=[],
            created_at=datetime.now(),
        )
        storage.add_rule(rule)

        called_args = {}

        async def mock_fetch_new_items(last_item_id=None, limit=50, last_fetched_at=None):
            called_args["last_item_id"] = last_item_id
            called_args["last_fetched_at"] = last_fetched_at
            return []

        mock_plugin_instance = MagicMock()
        mock_plugin_instance.fetch_new_items.side_effect = mock_fetch_new_items
        mock_plugin_instance.name = "youtube"

        mock_manifest = MagicMock()
        mock_manifest.source_plugin_class.return_value = mock_plugin_instance

        manifest = register({"youtube": mock_manifest})
        cmd = manifest.click_command

        def mock_get_storage():
            return storage

        with patch("commands.run.register.get_storage", mock_get_storage):
            runner = CliRunner()
            result = runner.invoke(cmd, ["--format", "json"])

            assert called_args.get("last_fetched_at") == last_fetch
            assert '"mode": "normal"' in result.output

    def test_force_mode_preserves_last_fetched_at(self, tmp_path):
        """Test that --force mode does NOT update the last_fetched_at."""
        from core.storage import MonitorStorage
        from commands.run.register import register

        db_path = tmp_path / "test.db"
        storage = MonitorStorage(db_path)

        original_time = datetime.now(timezone.utc)
        source = Source(
            id="test-src-force",
            plugin="youtube",
            identifier="UC123456789",
            description="Test Channel",
            last_fetched_at=original_time,
            created_at=datetime.now(),
        )
        storage.add_source(source)

        rule = Rule(
            id="test-rule-force",
            name="Test Rule",
            conditions={"all": [{"field": "source_plugin", "operator": "==", "value": "youtube"}]},
            action_ids=[],
            created_at=datetime.now(),
        )
        storage.add_rule(rule)

        items = [
            ItemMetadata(
                id="new-item-1",
                title="New Video 1",
                url="https://youtube.com/watch?v=1",
                published_at=datetime.now(timezone.utc),
                content_type="video",
                source_plugin="youtube",
                source_identifier="UC123456789",
                extra={},
            ),
        ]

        async def mock_fetch_new_items(last_item_id=None, limit=50, last_fetched_at=None):
            return items

        mock_plugin_instance = MagicMock()
        mock_plugin_instance.fetch_new_items.side_effect = mock_fetch_new_items
        mock_plugin_instance.name = "youtube"

        mock_manifest = MagicMock()
        mock_manifest.source_plugin_class.return_value = mock_plugin_instance

        manifest = register({"youtube": mock_manifest})
        cmd = manifest.click_command

        def mock_get_storage():
            return storage

        with patch("commands.run.register.get_storage", mock_get_storage):
            runner = CliRunner()
            result = runner.invoke(cmd, ["--force", "--format", "json"])

            updated_source = storage.get_source("test-src-force")
            assert updated_source.last_fetched_at == original_time

    def test_force_mode_limit_works(self, tmp_path):
        """Test that --limit works correctly with --force."""
        from core.storage import MonitorStorage
        from commands.run.register import register

        db_path = tmp_path / "test.db"
        storage = MonitorStorage(db_path)

        source = Source(
            id="test-src-limit",
            plugin="youtube",
            identifier="UC123456789",
            description="Test Channel",
            created_at=datetime.now(),
        )
        storage.add_source(source)

        rule = Rule(
            id="test-rule-limit",
            name="Test Rule",
            conditions={"all": [{"field": "source_plugin", "operator": "==", "value": "youtube"}]},
            action_ids=[],
            created_at=datetime.now(),
        )
        storage.add_rule(rule)

        called_args = {}

        async def mock_fetch_new_items(
            last_item_id=None, limit=50, last_fetched_at=None, force=False
        ):
            called_args["limit"] = limit
            return []

        mock_plugin_instance = MagicMock()
        mock_plugin_instance.fetch_new_items.side_effect = mock_fetch_new_items
        mock_plugin_instance.name = "youtube"

        mock_manifest = MagicMock()
        mock_manifest.source_plugin_class.return_value = mock_plugin_instance

        manifest = register({"youtube": mock_manifest})
        cmd = manifest.click_command

        def mock_get_storage():
            return storage

        with patch("commands.run.register.get_storage", mock_get_storage):
            runner = CliRunner()
            result = runner.invoke(cmd, ["--force", "--limit", "5", "--format", "json"])

            assert called_args.get("limit") == 5
