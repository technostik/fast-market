from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
