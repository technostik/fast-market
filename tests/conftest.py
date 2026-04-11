"""
Pytest configuration: redirect XDG dirs to tests/fixtures/ for full isolation.

All tests run against versioned fixture config and skills.
Real user config (~/.config/fast-market) and skills (~/.local/share/fast-market)
are never touched.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
FIXTURE_CONFIG = FIXTURES_DIR / "config"
FIXTURE_DATA = FIXTURES_DIR / "data"
FIXTURE_BIN = FIXTURES_DIR / "bin"

# Ensure local CLI entry packages are importable in tests.
for path in (TESTS_DIR, REPO_ROOT, REPO_ROOT / "task-cli", REPO_ROOT / "skill-cli", REPO_ROOT / "browser-cli"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


@pytest.fixture(autouse=True, scope="session")
def isolate_xdg(tmp_path_factory):
    """
    Redirect XDG dirs so all tests use fixture config + skills,
    with a tmp cache dir that is cleaned between sessions.

    scope=session: set once for the whole test run.
    autouse=True: applies to every test automatically.
    """
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    tmp_cache = tmp_path_factory.mktemp("cache")

    original_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(FIXTURE_BIN) + os.pathsep + original_path

    env_overrides = {
        "XDG_CONFIG_HOME": str(FIXTURE_CONFIG),
        "XDG_DATA_HOME": str(FIXTURE_DATA),
        "XDG_CACHE_HOME": str(tmp_cache),
    }

    original = {k: os.environ.get(k) for k in env_overrides}

    for k, v in env_overrides.items():
        os.environ[k] = v

    import common.core.paths as paths_mod

    importlib.reload(paths_mod)

    yield {
        "config": FIXTURE_CONFIG,
        "data": FIXTURE_DATA,
        "cache": tmp_cache,
        "bin": FIXTURE_BIN,
    }

    os.environ["PATH"] = original_path
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    importlib.reload(paths_mod)


@pytest.fixture
def workdir(tmp_path):
    """Fresh temp directory for each test's working directory."""
    return tmp_path


@pytest.fixture
def skills_dir(isolate_xdg):
    """Return the test skills directory."""
    from common.core.paths import get_skills_dir

    return get_skills_dir()


@pytest.fixture
def test_echo_skill(skills_dir):
    """Return the test-echo Skill object."""
    from core.skill import Skill

    return Skill.from_path(skills_dir / "test-echo")


@pytest.fixture
def test_fail_skill(skills_dir):
    from core.skill import Skill

    return Skill.from_path(skills_dir / "test-fail")


@pytest.fixture(autouse=True)
def cleanup_session_cache():
    """Clear session cache before each test to ensure clean state."""
    from common.core.paths import get_cache_dir

    cache_dir = get_cache_dir() / "skill-router"
    if cache_dir.exists():
        for f in cache_dir.glob("session-*.yaml"):
            f.unlink()
    yield


def pytest_addoption(parser):
    """Add provider filter for LLM integration module."""
    parser.addoption(
        "--provider",
        action="store",
        default="",
        help="Run tests with a single provider: xai, openai-compatible, or ollama.",
    )


def pytest_configure(config):
    """Register ad-hoc markers used by integration tests."""
    config.addinivalue_line(
        "markers",
        "slow: tests that perform real LLM calls and may take longer",
    )
    config.addinivalue_line(
        "markers",
        "order: keep declaration order for intentionally sequenced tests",
    )


