from __future__ import annotations

import importlib
import json

from core.pool_enrich import EnrichResult
from storage.sqlite_store import SQLiteStore


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_enrich_help_lists_command(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["enrich", "--help"])
    assert result.exit_code == 0, result.output
    assert "--concurrency" in result.output
    assert "--state" in result.output


def test_enrich_json_output(runner, mock_env, config_dict, monkeypatch):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item(
        "youtube", "v1", "pending",
        {"title": "Video One", "duration_seconds": 0},
        added_at="2026-08-01T00:00:00",
    )

    import core.pool_enrich as penrich

    monkeypatch.setattr(
        penrich,
        "enrich_pool_items",
        lambda store, source, **kw: EnrichResult(
            source=source, processed=1, enriched=1
        ),
    )

    main = _main_with_reload()
    result = runner.invoke(
        main, ["enrich", "--source", "youtube", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["source"] == "youtube"
    assert data["processed"] == 1
    assert data["enriched"] == 1


def test_enrich_failure_exits_nonzero(runner, mock_env, config_dict, monkeypatch):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item("youtube", "v1", "pending", {}, added_at="2026-08-01T00:00:00")

    import core.pool_enrich as penrich

    monkeypatch.setattr(
        penrich,
        "enrich_pool_items",
        lambda store, source, **kw: EnrichResult(
            source=source, processed=1, failed=1
        ),
    )

    main = _main_with_reload()
    result = runner.invoke(
        main, ["enrich", "--source", "youtube", "--format", "json"]
    )
    assert result.exit_code == 1


def test_enrich_source_defaults_to_youtube(runner, mock_env, config_dict, monkeypatch):
    import core.pool_enrich as penrich

    captured = {}

    def fake(store, source, **kw):
        captured["source"] = source
        return EnrichResult(source=source, processed=0)

    monkeypatch.setattr(penrich, "enrich_pool_items", fake)

    main = _main_with_reload()
    result = runner.invoke(main, ["enrich", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert captured["source"] == "youtube"


def test_enrich_aborted_exits_2(runner, mock_env, config_dict, monkeypatch):
    store = SQLiteStore(config_dict["db_path"])
    store.upsert_pool_item("youtube", "v1", "pending", {}, added_at="2026-08-01T00:00:00")

    import core.pool_enrich as penrich

    monkeypatch.setattr(
        penrich,
        "enrich_pool_items",
        lambda store, source, **kw: EnrichResult(
            source=source,
            processed=0,
            aborted=True,
            abort_reason="YouTube bot challenge — paused.",
        ),
    )

    main = _main_with_reload()
    result = runner.invoke(
        main, ["enrich", "--source", "youtube", "--format", "json"]
    )
    assert result.exit_code == 2
    assert "bot" in result.output.lower()
