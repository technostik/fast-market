from __future__ import annotations

from pathlib import Path

from common.webux.transcripts import (
    ass_to_plain_text,
    find_transcript,
    is_placeholder,
)


def _ass(tmp_path: Path, name: str = "clip.ass", text: str = "bonjour le monde") -> Path:
    path = tmp_path / name
    path.write_text(
        "[Script Info]\nTitle: x\n\n[Events]\n"
        f"Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{text}\n",
        encoding="utf-8",
    )
    return path


def test_is_placeholder():
    assert is_placeholder("(transcript unavailable)")
    assert is_placeholder("  (no transcript — manual title) ")
    assert not is_placeholder("bonjour")
    assert not is_placeholder("")


def test_ass_to_plain_text_strips_style_blocks(tmp_path: Path):
    ass = _ass(tmp_path, text="{\\b1}salut{\\b0} tout le monde")
    assert ass_to_plain_text(ass) == "salut tout le monde"


def test_find_transcript_prefers_meta_txt(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    txt = tmp_path / "clip_transcript.txt"
    txt.write_text("from meta", encoding="utf-8")
    (tmp_path / "clip.transcript.txt").write_text("sidecar", encoding="utf-8")

    found = find_transcript(src, {"transcript_txt": str(txt)}, "")
    assert found is not None
    assert found.origin == "meta-txt"
    assert found.path == txt
    assert found.text == "from meta"


def test_find_transcript_converts_and_materializes_ass(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    ass = _ass(tmp_path, text="depuis l'ass")

    found = find_transcript(src, {"transcript": str(ass)}, "")
    assert found is not None
    assert found.origin == "meta-ass"
    assert found.text == "depuis l'ass"
    txt = tmp_path / "clip_transcript.txt"
    assert found.path == txt
    assert txt.read_text(encoding="utf-8") == "depuis l'ass"


def test_find_transcript_prefers_ass_over_sidecar(tmp_path: Path):
    """The meta is authoritative; a stale sidecar must not win."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    ass = _ass(tmp_path, text="meta version")
    (tmp_path / "clip_transcript.txt").write_text("sidecar version", encoding="utf-8")

    found = find_transcript(src, {"transcript": str(ass)}, "")
    assert found is not None
    assert found.text == "meta version"


def test_find_transcript_sidecar_suffixes(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    (tmp_path / "clip.transcript.txt").write_text("dotted", encoding="utf-8")

    found = find_transcript(src, {}, "")
    assert found is not None
    assert found.origin == "sidecar"
    assert found.text == "dotted"


def test_find_transcript_falls_back_to_meta_text_and_materializes(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    found = find_transcript(src, {}, "stored text")
    assert found is not None
    assert found.origin == "meta-text"
    txt = tmp_path / "clip_transcript.txt"
    assert found.path == txt
    assert txt.read_text(encoding="utf-8") == "stored text"


def test_find_transcript_skips_placeholders(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    (tmp_path / "clip_transcript.txt").write_text("(transcript unavailable)", encoding="utf-8")

    assert find_transcript(src, {}, "(no transcript — manual title)") is None


def test_find_transcript_none_when_missing(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    assert find_transcript(src, {"transcript_txt": str(tmp_path / "gone.txt")}, "") is None


def test_find_transcript_materialize_false_keeps_files_untouched(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")
    ass = _ass(tmp_path, text="no write please")

    found = find_transcript(src, {"transcript": str(ass)}, "", materialize=False)
    assert found is not None
    assert found.text == "no write please"
    assert not (tmp_path / "clip_transcript.txt").exists()
