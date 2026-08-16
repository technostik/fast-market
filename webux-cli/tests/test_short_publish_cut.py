"""Tests for the optional one-time video cut feature (cut_time)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webux.short_publish.utils import _parse_timestamp


def test_parse_timestamp_mmss():
    assert _parse_timestamp("1:30") == 90.0


def test_parse_timestamp_hhmmss():
    assert _parse_timestamp("1:02:03") == 3723.0


def test_parse_timestamp_bare_seconds():
    assert _parse_timestamp("45") == 45.0
    assert _parse_timestamp("45.5") == 45.5


def test_parse_timestamp_empty_and_invalid():
    assert _parse_timestamp("") is None
    assert _parse_timestamp("   ") is None
    assert _parse_timestamp("abc") is None
    assert _parse_timestamp("1:xx") is None
