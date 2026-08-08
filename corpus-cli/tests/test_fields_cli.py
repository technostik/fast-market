from __future__ import annotations

import importlib
import json

from storage.sqlite_store import SQLiteStore


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def test_field_create_list(runner, mock_env, config_dict):
    main = _main_with_reload()
    result = runner.invoke(
        main,
        [
            "field",
            "create",
            "--name",
            "topic",
            "--applies-to",
            "youtube",
            "--description",
            "main topic",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "topic"
    assert data["applies_to"] == "youtube"

    result = runner.invoke(main, ["field", "list", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert [f["name"] for f in json.loads(result.output)] == ["topic"]


def test_field_create_duplicate_fails(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["field", "create", "--name", "topic"])
    result = runner.invoke(main, ["field", "create", "--name", "topic"])
    assert result.exit_code != 0
    assert "already defined" in result.output


def test_field_create_invalid_applies_to(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(
        main, ["field", "create", "--name", "topic", "--applies-to", "bogus"]
    )
    assert result.exit_code != 0
    assert "bogus" in result.output


def test_field_delete(runner, mock_env):
    main = _main_with_reload()
    runner.invoke(main, ["field", "create", "--name", "topic"])
    result = runner.invoke(main, ["field", "delete", "--name", "topic"])
    assert result.exit_code == 0, result.output
    assert "Deleted field 'topic'" in result.output

    result = runner.invoke(main, ["field", "list", "--format", "json"])
    assert json.loads(result.output) == []


def test_field_set_and_missing(runner, mock_env, config_dict):
    from core.models import Document

    store = SQLiteStore(config_dict["db_path"])
    store.upsert_document(
        Document(
            source_plugin="obsidian",
            source_id="note1",
            handle="ob-note1",
            title="Note One",
            raw_text="hello world content",
        ),
        "h-note1",
    )
    main = _main_with_reload()
    runner.invoke(main, ["field", "create", "--name", "topic"])

    result = runner.invoke(main, ["field", "missing", "--name", "topic", "--format", "json"])
    assert result.exit_code == 0, result.output
    missing = json.loads(result.output)
    assert len(missing) >= 1
    target = missing[0]

    result = runner.invoke(
        main,
        [
            "field",
            "set",
            "--name",
            "topic",
            "--source",
            target["source_plugin"],
            "--id",
            target["source_id"],
            "--value",
            '"AI"',
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    set_doc = json.loads(result.output)
    assert set_doc["metadata"]["topic"] == "AI"

    result = runner.invoke(main, ["field", "missing", "--name", "topic", "--format", "json"])
    remaining = json.loads(result.output)
    assert target["source_id"] not in [d["source_id"] for d in remaining]


def test_sync_field_fills_via_operation(runner, mock_env, config_dict, monkeypatch):
    """corpus sync --field summary runs the summarize operation on docs missing it."""
    from core.models import Document
    from operations.summarize.register import SummarizeOperation

    store = SQLiteStore(config_dict["db_path"])
    store.upsert_document(
        Document(
            source_plugin="obsidian",
            source_id="note1",
            handle="ob-note1",
            title="Note One",
            raw_text="hello world content",
        ),
        "h-note1",
    )
    monkeypatch.setattr(
        SummarizeOperation, "run", lambda self, doc: "summarized text"
    )

    main = _main_with_reload()
    runner.invoke(main, ["field", "create", "--name", "summary"])

    result = runner.invoke(
        main, ["sync", "--source", "obsidian", "--field", "summary", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]["source"] == "obsidian"
    assert data[0]["indexed"] >= 1

    doc = store.get_document("obsidian", "note1")
    assert doc["metadata"]["summary"] == "summarized text"


def test_sync_field_requires_declared_field(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(
        main, ["sync", "--source", "obsidian", "--field", "summary"]
    )
    assert result.exit_code != 0
    assert "is not defined" in result.output


def test_sync_field_unknown_field(runner, mock_env):
    main = _main_with_reload()
    result = runner.invoke(main, ["field", "create", "--name", "summary"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        main, ["sync", "--source", "obsidian", "--field", "bogus"]
    )
    assert result.exit_code != 0
    assert "No registered operation" in result.output
