from __future__ import annotations

import importlib
import json
from pathlib import Path

from storage.sqlite_store import SQLiteStore


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main


def _add_args(tmp_path: Path, transcript: str = "Hello corpus world.", **over) -> list[str]:
    transcript_file = tmp_path / "transcript.txt"
    transcript_file.write_text(transcript, encoding="utf-8")
    args = [
        "add",
        "--source", "youtube",
        "--id", "addvid00001",
        "--url", "https://www.youtube.com/watch?v=addvid00001",
        "--title", "My added video",
        "--transcript-file", str(transcript_file),
        "--privacy", "unlisted",
        "--duration", "542",
        "--format", "json",
    ]
    for key, value in over.items():
        args += [f"--{key.replace('_', '-')}", str(value)]
    return args


def test_add_indexes_document(runner, mock_env, tmp_path):
    description_file = tmp_path / "description.txt"
    description_file.write_text("The video description.", encoding="utf-8")

    main = _main_with_reload()
    result = runner.invoke(
        main,
        _add_args(tmp_path) + ["--description-file", str(description_file)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["source"] == "youtube"
    assert data["source_id"] == "addvid00001"
    assert data["handle"].startswith("yt-")
    assert data["indexed"] is True
    assert data["chunks"] >= 1
    assert data["url"] == "https://www.youtube.com/watch?v=addvid00001"

    doc = runner.invoke(
        main,
        ["get-from-source", "youtube", "addvid00001", "--what", "all", "--format", "json"],
    )
    assert doc.exit_code == 0, doc.output
    stored = json.loads(doc.output)
    assert stored["title"] == "My added video"
    assert stored["raw_text"] == "Hello corpus world."
    assert stored["privacy_status"] == "unlisted"
    assert stored["duration_seconds"] == 542
    assert stored["metadata"]["description"] == "The video description."
    assert stored["metadata"]["url"] == "https://www.youtube.com/watch?v=addvid00001"


def test_add_marks_pool_item_synced(runner, mock_env, tmp_path):
    main = _main_with_reload()
    result = runner.invoke(main, _add_args(tmp_path))
    assert result.exit_code == 0, result.output

    from common.core.config import load_config

    store = SQLiteStore(load_config()["db_path"])
    items = store.get_pool_items(plugin_name="youtube", status=None)
    item = next(i for i in items if i["source_id"] == "addvid00001")
    assert item["status"] == "synced"
    assert item["metadata"]["title"] == "My added video"


def test_add_twice_is_idempotent(runner, mock_env, tmp_path):
    main = _main_with_reload()
    first = runner.invoke(main, _add_args(tmp_path))
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)["indexed"] is True

    second = runner.invoke(main, _add_args(tmp_path))
    assert second.exit_code == 0, second.output
    data = json.loads(second.output)
    assert data["indexed"] is False
    assert data["chunks"] == 0

    docs = runner.invoke(main, ["list", "--format", "json"])
    assert docs.exit_code == 0, docs.output
    matching = [d for d in json.loads(docs.output) if d.get("source_id") == "addvid00001"]
    assert len(matching) == 1


def test_add_rejects_empty_transcript(runner, mock_env, tmp_path):
    main = _main_with_reload()
    result = runner.invoke(main, _add_args(tmp_path, transcript="   "))
    assert result.exit_code != 0
    assert "Transcript is empty" in result.output


def test_add_rejects_inline_and_file(runner, mock_env, tmp_path):
    main = _main_with_reload()
    result = runner.invoke(
        main, _add_args(tmp_path) + ["--transcript", "inline text"]
    )
    assert result.exit_code != 0
    assert "not both" in result.output
