"""Tests for the post command thread splitting and basic CLI structure."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from commands.post.register import _split_thread


# ---------------------------------------------------------------------------
# Thread splitting
# ---------------------------------------------------------------------------
class TestSplitThread:
    def test_single_message(self):
        assert _split_thread("Hello world") == ["Hello world"]

    def test_two_parts(self):
        msg = "First tweet\n\n---\n\nSecond tweet"
        result = _split_thread(msg)
        assert len(result) == 2
        assert result[0] == "First tweet"
        assert result[1] == "Second tweet"

    def test_three_parts(self):
        msg = "Tweet 1\n---\nTweet 2\n---\nTweet 3"
        result = _split_thread(msg)
        assert len(result) == 3
        assert result[0] == "Tweet 1"
        assert result[1] == "Tweet 2"
        assert result[2] == "Tweet 3"

    def test_empty_parts_ignored(self):
        msg = "Tweet 1\n---\n\n---\nTweet 3"
        result = _split_thread(msg)
        assert len(result) == 2
        assert result == ["Tweet 1", "Tweet 3"]

    def test_no_trailing_content(self):
        msg = "Tweet 1\n---\n"
        result = _split_thread(msg)
        assert result == ["Tweet 1"]
