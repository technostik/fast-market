from __future__ import annotations

from pathlib import Path

import pytest

from core.substitution import (
    extract_placeholders,
    resolve_arguments,
    resolve_inline_file_references,
)


def test_extract_placeholders_sorted_unique():
    assert extract_placeholders("Hello {name} {name} {thing}") == ["name", "thing"]


def test_resolve_arguments_literal():
    assert resolve_arguments("Hello {name}", {"name": "world"}) == "Hello world"


def test_resolve_arguments_file(tmp_path: Path):
    file_path = tmp_path / "input.txt"
    file_path.write_text("example", encoding="utf-8")
    assert (
        resolve_arguments("Read {content}", {"content": f"@{file_path}"})
        == "Read example"
    )


def test_resolve_arguments_missing_file():
    with pytest.raises(FileNotFoundError):
        resolve_arguments("Read {content}", {"content": "@missing.txt"})


def test_resolve_arguments_missing_placeholder():
    with pytest.raises(ValueError):
        resolve_arguments("Hello {name}", {})


def test_resolve_inline_file_references_basic(tmp_path: Path):
    file_path = tmp_path / "config.yaml"
    file_path.write_text("key: value", encoding="utf-8")
    template = f"Review this: @{file_path.name}"
    result, _ = resolve_inline_file_references(template, tmp_path)
    assert result == "Review this: key: value"


def test_resolve_inline_file_references_nested(tmp_path: Path):
    subdir = tmp_path / "docs"
    subdir.mkdir()
    file_path = subdir / "readme.txt"
    file_path.write_text("Hello World", encoding="utf-8")
    template = "Read @docs/readme.txt"
    result, _ = resolve_inline_file_references(template, tmp_path)
    assert result == "Read Hello World"


def test_resolve_inline_file_references_not_found(tmp_path: Path):
    template = "File @missing.txt exists"
    result, files = resolve_inline_file_references(template, tmp_path)
    assert result == "File @missing.txt exists"
    assert len(files) == 0


def test_resolve_inline_file_references_absolute_path_rejected(tmp_path: Path):
    template = "File @/etc/passwd should not be read"
    result, files = resolve_inline_file_references(template, tmp_path)
    assert result == "File @/etc/passwd should not be read"
    assert len(files) == 0


def test_resolve_inline_file_references_escaped(tmp_path: Path):
    template = r"Email: user\@example.com"
    result, _ = resolve_inline_file_references(template, tmp_path)
    assert result == "Email: user@example.com"


def test_resolve_inline_file_references_multiple(tmp_path: Path):
    file1 = tmp_path / "a.txt"
    file1.write_text("content A", encoding="utf-8")
    file2 = tmp_path / "b.txt"
    file2.write_text("content B", encoding="utf-8")
    template = "@a.txt and @b.txt"
    result, files = resolve_inline_file_references(template, tmp_path)
    assert result == "content A and content B"
    assert len(files) == 2


def test_resolve_inline_file_references_with_parameters(tmp_path: Path):
    file_path = tmp_path / "data.json"
    file_path.write_text("[1, 2, 3]", encoding="utf-8")
    template = "Data: @data.json\nTopic: {topic}"
    result = resolve_arguments(template, {"topic": "testing"}, tmp_path)
    assert result == "Data: [1, 2, 3]\nTopic: testing"


def test_resolve_inline_file_references_combined_with_args(tmp_path: Path):
    file_path = tmp_path / "input.txt"
    file_path.write_text("file content", encoding="utf-8")
    template = "Inline: @input.txt\nArg: {value}"
    result = resolve_arguments(template, {"value": "arg value"}, tmp_path)
    assert result == "Inline: file content\nArg: arg value"
