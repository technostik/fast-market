from __future__ import annotations

from pathlib import Path

import pytest

from core.substitution import extract_placeholders, resolve_arguments


def test_extract_placeholders_sorted_unique():
    assert extract_placeholders("Hello {name} {name} {thing}") == ["name", "thing"]


def test_resolve_arguments_literal():
    assert resolve_arguments("Hello {name}", {"name": "world"}) == "Hello world"


def test_resolve_arguments_file(tmp_path: Path):
    file_path = tmp_path / "input.txt"
    file_path.write_text("example", encoding="utf-8")
    assert resolve_arguments("Read {content}", {"content": f"@{file_path}"}) == "Read example"


def test_resolve_arguments_missing_file():
    with pytest.raises(FileNotFoundError):
        resolve_arguments("Read {content}", {"content": "@missing.txt"})


def test_resolve_arguments_missing_placeholder():
    with pytest.raises(ValueError):
        resolve_arguments("Hello {name}", {})
