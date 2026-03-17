from __future__ import annotations

import warnings
from pathlib import Path


from core.config import load_config
from core.paths import get_fastmarket_dir, get_tool_cache_dir, get_tool_config, get_tool_data_dir
from storage.sqlite_store import SQLiteStore


def test_paths_follow_xdg(monkeypatch, tmp_path: Path):
    data_home = tmp_path / "xdg_data"
    cache_home = tmp_path / "xdg_cache"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))

    assert get_fastmarket_dir() == data_home / "fast-market"
    assert get_tool_config("corpus") == data_home / "fast-market" / "config" / "corpus.yaml"

    corpus_dir = get_tool_data_dir("corpus")
    marketing_dir = get_tool_data_dir("marketing")
    assert corpus_dir == data_home / "fast-market" / "data" / "corpus"
    assert marketing_dir == data_home / "fast-market" / "data" / "marketing"
    assert corpus_dir.exists()
    assert marketing_dir.exists()

    cache_dir = get_tool_cache_dir("corpus")
    assert cache_dir == cache_home / "fast-market" / "corpus"
    assert cache_dir.exists()


def test_load_config_from_override_dir(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    cfg_path = config_dir / "corpus.yaml"
    cfg_path.write_text("db_path: :memory:\n", encoding="utf-8")

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(config_dir))
    loaded = load_config()
    assert loaded["db_path"] == ":memory:"


def test_deprecated_local_config_still_supported(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("db_path: :memory:\n", encoding="utf-8")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        loaded = load_config()

    assert loaded["db_path"] == ":memory:"
    assert any("deprecated" in str(w.message).lower() for w in captured)


def test_sqlite_store_default_path_is_tool_data(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    store = SQLiteStore()
    row = store.conn.execute("PRAGMA database_list").fetchone()
    assert row is not None
    db_path = Path(row[2])
    assert db_path.name == "corpus.db"
    assert "fast-market/data/corpus" in str(db_path)


def test_tool_data_isolation(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    corpus_dir = get_tool_data_dir("corpus")
    marketing_dir = get_tool_data_dir("marketing")

    (corpus_dir / "corpus.db").write_text("dummy", encoding="utf-8")
    assert (marketing_dir / "corpus.db").exists() is False
