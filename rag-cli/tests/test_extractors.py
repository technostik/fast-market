from __future__ import annotations

from core.extractors import extract_markdown, _content_hash, discover_files
from pathlib import Path


def test_extract_markdown_basic(sample_md_path: Path):
    doc = extract_markdown(sample_md_path)
    assert doc.title == "Sample Document"
    assert len(doc.full_text) > 0
    assert doc.content_hash == _content_hash(doc.full_text)
    assert len(doc.pages) == 1
    assert doc.pages[0].page_number == 1


def test_extract_markdown_content_hash_deterministic(sample_md_path: Path):
    doc1 = extract_markdown(sample_md_path)
    doc2 = extract_markdown(sample_md_path)
    assert doc1.content_hash == doc2.content_hash


def test_extract_markdown_title_from_heading(sample_md_path: Path):
    doc = extract_markdown(sample_md_path)
    assert doc.title == "Sample Document"


def test_extract_unsupported_filetype(tmp_path: Path):
    from core.extractors import extract_local_file
    import pytest

    bad_file = tmp_path / "test.xyz"
    bad_file.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_local_file(bad_file)


def test_discover_files_single_file(sample_md_path: Path):
    files = discover_files(sample_md_path)
    assert files == [sample_md_path]


def test_discover_files_unsupported_file(tmp_path: Path):
    bad_file = tmp_path / "test.xyz"
    bad_file.write_text("hello")
    files = discover_files(bad_file)
    assert files == []


def test_discover_files_directory(tmp_path: Path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "c.txt").write_text("skip me")
    (tmp_path / ".hidden.md").write_text("# Hidden")

    files = discover_files(tmp_path)
    names = [f.name for f in files]
    assert "a.md" in names
    assert "b.pdf" in names
    assert "c.txt" not in names
    assert ".hidden.md" not in names


def test_discover_files_recursive(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "root.md").write_text("# Root")
    (sub / "nested.md").write_text("# Nested")

    files = discover_files(tmp_path)
    names = [f.name for f in files]
    assert "root.md" in names
    assert "nested.md" in names


def test_discover_files_empty_directory(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    files = discover_files(empty)
    assert files == []


def test_discover_files_nonexistent_path(tmp_path: Path):
    import pytest
    with pytest.raises(ValueError, match="Path not found"):
        discover_files(tmp_path / "nope")
