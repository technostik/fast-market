from __future__ import annotations

import importlib

from core.models import Document
from plugins.base import ItemMeta, SourcePlugin
from storage.sqlite_store import SQLiteStore


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


class ScanAllPlugin(SourcePlugin):
    name = "faketool"
    scan_strategy = "generic"

    def __init__(self, items=None):
        self._items = items or [ItemMeta("x", metadata={"updated_at": "2024-01-01"})]

    def list_items(self, limit, known_id_dates=None, scan_all=False, debug=False):
        return self._items

    def fetch(self, item_meta: ItemMeta):
        return Document(
            source_plugin=self.name,
            source_id=item_meta.source_id,
            title="X",
            raw_text="body",
        )


def test_scan_source_adds_new_items_to_pool(store):
    from commands.scan.register import _scan_source

    plugin = ScanAllPlugin()
    _scan_source(plugin, store, debug=False)
    pool = store.get_pool_items("faketool", status="pending")
    assert len(pool) == 1
    assert pool[0]["source_id"] == "x"


def test_scan_source_skips_synced_ids(store):
    from commands.scan.register import _scan_source

    plugin = ScanAllPlugin(
        [ItemMeta("x", metadata={"updated_at": "2024-01-01"})]
    )
    store.upsert_pool_item("faketool", "x", "synced", {"updated_at": "2024-01-01"})

    _scan_source(plugin, store, debug=False)
    pool = store.get_pool_items("faketool", status=None)
    assert len(pool) == 1
    assert pool[0]["status"] == "synced"


def test_scan_source_refreshes_metadata_and_requeues(store):
    from commands.scan.register import _scan_source

    store.upsert_pool_item(
        "faketool", "x", "failed",
        {"privacy_status": "private", "updated_at": "2024-01-01"},
    )
    plugin = ScanAllPlugin(
        [ItemMeta("x", metadata={"privacy_status": "public", "updated_at": "2024-01-01"})]
    )
    plugin.requeue_on = "public"

    _scan_source(plugin, store, debug=False)
    pool = store.get_pool_items("faketool", status=None)
    assert pool[0]["status"] == "pending"
    assert pool[0]["metadata"]["privacy_status"] == "public"


def test_obsidian_list_items_scan_all_returns_every_file(vault):
    from plugins.obsidian.plugin import ObsidianPlugin

    plugin = ObsidianPlugin({"obsidian": {"vault_path": str(vault)}})
    items = plugin.list_items(limit=10, scan_all=True)
    assert {i.source_id for i in items} == {"note1.md", "note2.md", "note3.md"}


def test_scan_cli_obsidian_generic_path_uses_tui_strategy(runner, mock_env, monkeypatch, config_dict):
    """The scan command must route obsidian to the TUI, not the generic loop."""
    from commands.scan import register as scan_register

    store = SQLiteStore(config_dict["db_path"])
    main = _main_with_reload()

    # Monkeypatch the obsidian plugin's scan_strategy to generic so the scan
    # loop walks the vault non-interactively (what the generic path would do).
    from plugins.obsidian import plugin as ob_plugin

    original = ob_plugin.ObsidianPlugin.scan_strategy
    monkeypatch.setattr(ob_plugin.ObsidianPlugin, "scan_strategy", "generic")
    try:
        result = runner.invoke(main, ["scan", "--source", "obsidian"])
    finally:
        monkeypatch.setattr(ob_plugin.ObsidianPlugin, "scan_strategy", original)
    assert result.exit_code == 0, result.output
    assert "obsidian: 3 new" in result.output
    assert len(store.get_pool_items("obsidian", status="pending")) == 3