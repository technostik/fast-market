from __future__ import annotations

import warnings
from pathlib import Path


from common import structlog
from common.storage.base import create_sqlite_engine
from core.config import load_config
from core.paths import (
    get_fastmarket_dir,
    get_tool_cache_dir,
    get_tool_config,
    get_tool_data_dir,
)
from plugins.obsidian.plugin import ObsidianPlugin
from plugins.youtube.plugin import YouTubeTransport
from storage.sqlite_store import SQLiteStore


def test_paths_follow_xdg(monkeypatch, tmp_path: Path):
    config_home = tmp_path / "xdg_config"
    data_home = tmp_path / "xdg_data"
    cache_home = tmp_path / "xdg_cache"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))

    assert get_fastmarket_dir() == data_home / "fast-market"
    assert (
        get_tool_config("corpus")
        == config_home / "fast-market" / "corpus" / "config.yaml"
    )

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
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    config_dir = home / "cfg"
    config_dir.mkdir(parents=True)
    cfg_path = config_dir / "corpus.yaml"
    cfg_path.write_text('db_path: ":memory:"\n', encoding="utf-8")

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", "~/cfg")
    loaded = load_config()
    assert loaded["db_path"] == ":memory:"


def test_paths_expand_tilde_in_xdg_env(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", "~/.custom_data")
    monkeypatch.setenv("XDG_CACHE_HOME", "~/.custom_cache")

    assert get_fastmarket_dir() == home / ".custom_data" / "fast-market"
    assert (
        get_tool_cache_dir("corpus")
        == home / ".custom_cache" / "fast-market" / "corpus"
    )


def test_deprecated_local_config_still_supported(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text('db_path: ":memory:"\n', encoding="utf-8")

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


def test_sqlite_store_expands_tilde_db_path(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    store = SQLiteStore("~/.local/share/fast-market/data/corpus/corpus.db")
    row = store.conn.execute("PRAGMA database_list").fetchone()
    assert row is not None
    db_path = Path(row[2])
    assert (
        db_path
        == home / ".local" / "share" / "fast-market" / "data" / "corpus" / "corpus.db"
    )


def test_tool_data_isolation(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    corpus_dir = get_tool_data_dir("corpus")
    marketing_dir = get_tool_data_dir("marketing")

    (corpus_dir / "corpus.db").write_text("dummy", encoding="utf-8")
    assert (marketing_dir / "corpus.db").exists() is False


def test_obsidian_plugin_expands_tilde_vault_path(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    vault = home / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    plugin = ObsidianPlugin({"obsidian": {"vault_path": "~/vault"}})
    assert plugin.vault == vault


def test_youtube_transport_expands_tilde_client_secret_path(
    monkeypatch, tmp_path: Path
):
    home = tmp_path / "home"
    secrets_dir = home / "secrets"
    secrets_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    transport = YouTubeTransport(client_secret_path="~/secrets/client_secret.json")
    token_path = Path(transport.client_secret_path).expanduser().parent / "token.json"
    assert token_path == secrets_dir / "token.json"


def test_common_structlog_logger_available():
    logger = structlog.get_logger("test")
    assert logger is not None


def test_common_storage_engine_respects_custom_path(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    engine = create_sqlite_engine(
        "corpus", db_path="~/.local/share/fast-market/data/corpus/custom.db"
    )
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql("PRAGMA database_list").fetchone()
    finally:
        engine.dispose()
    assert row is not None
    db_path = Path(row[2])
    assert (
        db_path
        == home / ".local" / "share" / "fast-market" / "data" / "corpus" / "custom.db"
    )
