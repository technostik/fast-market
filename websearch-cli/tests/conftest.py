from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TESTS_DIR = Path(__file__).parent
FIXTURE_CONFIG = TESTS_DIR / "fixtures" / "config"
FIXTURE_DATA = TESTS_DIR / "fixtures" / "data"


@pytest.fixture(autouse=True, scope="session")
def isolate_xdg(tmp_path_factory):
    """Redirect XDG dirs to fixture paths and pin profile to 'test'."""
    tmp_cache = tmp_path_factory.mktemp("cache")
    env_overrides = {
        "XDG_CONFIG_HOME": str(FIXTURE_CONFIG),
        "XDG_DATA_HOME": str(FIXTURE_DATA),
        "XDG_CACHE_HOME": str(tmp_cache),
        "FASTMARKET_PROFILE": "test",
    }
    original = {k: os.environ.get(k) for k in env_overrides}
    for k, v in env_overrides.items():
        os.environ[k] = v

    import common.core.paths as paths_mod

    importlib.reload(paths_mod)

    yield {"config": FIXTURE_CONFIG, "data": FIXTURE_DATA, "cache": tmp_cache}

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(paths_mod)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _main_with_reload():
    import cli.main as cli_mod

    importlib.reload(cli_mod)
    return cli_mod.main
