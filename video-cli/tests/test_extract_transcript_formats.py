"""Unit tests for extract-transcript format selection (no Whisper/ffmpeg needed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import commands.extract_transcript.register as etr  # noqa: E402


@pytest.fixture
def command():
    return etr.register({}).click_command


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "talk.mp4"
    path.write_bytes(b"fake-video")
    return path


SEGMENTS = [
    {
        "start": 0.0,
        "end": 1.0,
        "text": "Salut.",
        "words": [{"word": "Salut.", "start": 0.0, "end": 1.0}],
    },
    {
        "start": 1.5,
        "end": 2.0,
        "text": "Toi",
        "words": [{"word": "Toi", "start": 1.5, "end": 2.0}],
    },
]


def test_parse_formats_comma_and_repeat():
    assert etr._parse_formats(("json,txt",), None) == ["json", "txt"]
    assert etr._parse_formats(("json", "txt"), None) == ["json", "txt"]
    assert etr._parse_formats(("json, txt,json",), None) == ["json", "txt"]
    assert etr._parse_formats((), "/tmp/out.json") == ["json"]
    assert etr._parse_formats((), None) == ["srt"]


def test_parse_formats_rejects_unknown():
    import click

    with pytest.raises(click.BadParameter):
        etr._parse_formats(("json,bogus",), None)


def test_multiple_formats_transcribe_once(command, video, tmp_path):
    base = tmp_path / "talk"
    with patch.object(etr, "_transcribe_word_segments", return_value=SEGMENTS) as transcribe:
        result = CliRunner().invoke(
            command,
            [str(video), "-f", "json,txt", "-o", str(base.with_suffix(".json"))],
        )
    assert result.exit_code == 0, result.output
    transcribe.assert_called_once()

    json_path = tmp_path / "talk.json"
    txt_path = tmp_path / "talk.txt"
    assert json_path.exists() and txt_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["text"] == "Salut. Toi"
    assert payload["words"][1] == {"word": "Toi", "start": 1.5, "end": 2.0}
    assert txt_path.read_text(encoding="utf-8") == "Salut.\nToi"
    # One final path per format on stdout.
    assert str(json_path) in result.output
    assert str(txt_path) in result.output


def test_multiple_formats_without_output_uses_input_stem(command, video):
    with patch.object(etr, "_transcribe_word_segments", return_value=SEGMENTS):
        result = CliRunner().invoke(command, [str(video), "-f", "srt,txt"])
    assert result.exit_code == 0, result.output
    assert (video.parent / "talk.srt").exists()
    assert (video.parent / "talk.txt").exists()


def test_single_format_keeps_exact_output_path(command, video, tmp_path):
    out = tmp_path / "custom.json"
    with patch.object(etr, "transcribe_to_json") as single:
        result = CliRunner().invoke(command, [str(video), "-f", "json", "-o", str(out)])
    assert result.exit_code == 0, result.output
    single.assert_called_once()
    assert single.call_args.args[1] == str(out.resolve())


def test_multiple_formats_rejected_with_modal(command, video):
    result = CliRunner().invoke(command, [str(video), "-f", "json,txt", "--modal"])
    assert result.exit_code != 0
    assert "local-only" in result.output
