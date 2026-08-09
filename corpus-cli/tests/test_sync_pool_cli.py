from __future__ import annotations

import importlib
import json

from storage.sqlite_store import SQLiteStore


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_sync_handles_syncs_only_selected_pool_items(runner, mock_env, config_dict):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item(
        "youtube", "vid1", "pending",
        {"title": "Video One", "privacy_status": "public"},
        added_at="2026-08-01T00:00:00",
    )
    store.upsert_pool_item(
        "youtube", "vid2", "pending",
        {"title": "Video Two", "privacy_status": "public"},
        added_at="2026-08-02T00:00:00",
    )

    main = _main_with_reload()
    result = runner.invoke(
        main,
        [
            "sync",
            "--source",
            "youtube",
            "--handles",
            "pool:youtube:vid1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "youtube"
    assert data[0]["indexed"] == 1

    pool = {i["source_id"]: i for i in store.get_pool_items("youtube", status=None)}
    assert pool["vid1"]["status"] == "synced"
    assert pool["vid2"]["status"] == "pending"  # untouched


def test_sync_handles_no_match_warns(runner, mock_env, config_dict):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item(
        "youtube", "vid1", "pending",
        {"title": "Video One", "privacy_status": "public"},
        added_at="2026-08-01T00:00:00",
    )

    main = _main_with_reload()
    result = runner.invoke(
        main,
        [
            "sync",
            "--source",
            "youtube",
            "--handles",
            "pool:youtube:nope",
            "--format",
            "json",
        ],
    )
    assert result.exit_code != 0
    assert "No matching pool items" in json.dumps(result.output)


def test_sync_handles_include_failed_and_excluded(runner, mock_env, config_dict):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item(
        "youtube", "vid1", "failed",
        {"title": "Video One", "privacy_status": "public"},
        added_at="2026-08-01T00:00:00",
    )

    main = _main_with_reload()
    result = runner.invoke(
        main,
        [
            "sync",
            "--source",
            "youtube",
            "--handles",
            "pool:youtube:vid1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["indexed"] == 1
