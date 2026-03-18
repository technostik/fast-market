from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.embedder import Embedder
from plugins.youtube.plugin import Transport
from storage.sqlite_store import SQLiteStore


class DummyEmbedder(Embedder):
    def _lazy_model(self):
        return self

    def encode(self, texts, batch_size=32):
        return [[float(len(t)), 1.0] for t in texts]


class MockYouTubeTransport(Transport):
    """Returns 2 deterministic fake videos with transcripts."""

    def get_uploads_playlist(self, channel_id: str) -> str:
        return "PLfake"

    def iter_playlist_pages(self, playlist_id: str):
        yield [
            {"snippet": {
                "resourceId": {"videoId": "vid1"},
                "title": "Video One",
                "publishedAt": "2024-01-15T00:00:00Z",
            }},
            {"snippet": {
                "resourceId": {"videoId": "vid2"},
                "title": "Video Two",
                "publishedAt": "2024-02-20T00:00:00Z",
            }},
        ]

    def get_video_details(self, video_ids: list[str]) -> dict:
        return {
            vid: {
                "contentDetails": {"duration": "PT5M30S"},
                "snippet": {
                    "description": f"Description for {vid}",
                    "title": f"Video {vid}",
                    "publishedAt": "2024-01-15T00:00:00Z",
                },
                "status": {"privacyStatus": "public"},
            }
            for vid in video_ids
        }

    def get_transcript(self, video_id: str, cookies) -> str:
        return f"transcript content for video {video_id}"

    def download_audio(self, video_id: str, cookies):
        return None


@pytest.fixture
def store() -> SQLiteStore:
    return SQLiteStore(":memory:")


@pytest.fixture
def embedder() -> DummyEmbedder:
    return DummyEmbedder()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "data"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal Obsidian vault with 3 notes."""
    (tmp_path / "note1.md").write_text("# Hello World\nhello world content", encoding="utf-8")
    (tmp_path / "note2.md").write_text("# Foo Bar\nfoo bar baz content", encoding="utf-8")
    (tmp_path / "note3.md").write_text(
        "---\ntags:\n  - test\n---\n# Tagged Note\ntagged content", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def config_path(tmp_path: Path, vault: Path) -> Path:
    """Write a minimal config.yaml to tmp_path."""
    import yaml as _yaml

    cfg = {
        "db_path": str(tmp_path / "test.db"),
        "embed_batch_size": 2,
        "embeddings": {"model": "paraphrase-multilingual-mpnet-base-v2", "server_port": 8765, "batch_size": 2},
        "obsidian": {"vault_path": str(vault)},
        "youtube": {"channel_id": "UC_fake", "client_secret_path": ""},
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_yaml.safe_dump(cfg), encoding="utf-8")
    return cfg_path




@pytest.fixture
def config_dict(tmp_path: Path, vault: Path) -> dict:
    return {
        "db_path": str(tmp_path / "test.db"),
        "embed_batch_size": 2,
        "embeddings": {"model": "paraphrase-multilingual-mpnet-base-v2", "server_port": 8765, "batch_size": 2},
        "obsidian": {"vault_path": str(vault)},
        "youtube": {"channel_id": "UC_fake", "client_secret_path": ""},
    }

@pytest.fixture
def mock_env(config_path: Path, config_dict: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch cwd + YouTube transport + embedder for integration tests."""
    monkeypatch.chdir(tmp_path)

    from plugins.youtube import plugin as yt_plugin

    original_init = yt_plugin.YouTubePlugin.__init__

    def patched_init(self, config, transport=None):
        original_init(self, config, transport=MockYouTubeTransport())

    monkeypatch.setattr(yt_plugin.YouTubePlugin, "__init__", patched_init)

    import core.embedder as emb_mod
    import core.config as cfg_mod
    import common.core.config as common_cfg_mod

    monkeypatch.setattr(emb_mod, "Embedder", DummyEmbedder)
    monkeypatch.setattr(cfg_mod, "load_config", lambda path="config.yaml": config_dict)
    monkeypatch.setattr(common_cfg_mod, "load_config", lambda path="config.yaml": config_dict)

    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def api_client(mock_env):
    import importlib

    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import api.server as srv

    importlib.reload(srv)
    return TestClient(srv.app)
