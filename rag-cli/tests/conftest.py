from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"


@pytest.fixture(autouse=True, scope="session")
def isolate_xdg(tmp_path_factory):
    tmp_config = tmp_path_factory.mktemp("config")
    tmp_data = tmp_path_factory.mktemp("data")
    tmp_cache = tmp_path_factory.mktemp("cache")
    env_overrides = {
        "XDG_CONFIG_HOME": str(tmp_config),
        "XDG_DATA_HOME": str(tmp_data),
        "XDG_CACHE_HOME": str(tmp_cache),
        "FASTMARKET_PROFILE": "test",
    }
    original = {k: os.environ.get(k) for k in env_overrides}
    for k, v in env_overrides.items():
        os.environ[k] = v

    import common.core.paths as paths_mod

    importlib.reload(paths_mod)

    yield {"config": tmp_config, "data": tmp_data, "cache": tmp_cache}

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(paths_mod)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def in_memory_store():
    from storage.store import RagStore, create_memory_engine, make_session_factory

    engine = create_memory_engine()
    sf = make_session_factory(engine)
    return RagStore(sf)


@pytest.fixture
def sample_md_path() -> Path:
    return FIXTURES_DIR / "sample.md"


@pytest.fixture
def sample_md_content() -> str:
    return (FIXTURES_DIR / "sample.md").read_text(encoding="utf-8")
