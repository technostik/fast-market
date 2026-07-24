from __future__ import annotations

from core.extractors import extract_markdown, _content_hash
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
