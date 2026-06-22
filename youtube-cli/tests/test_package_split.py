from __future__ import annotations

from pathlib import Path


def test_youtube_package_no_video_processing_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    commands = root / "commands"
    assert not (commands / "remove_silence").exists()
    assert not (commands / "extract_transcript").exists()
    assert not (commands / "burn_subtitles").exists()
    assert not (commands / "modal_diagnose").exists()
    assert not (root / "modal_client").exists()
