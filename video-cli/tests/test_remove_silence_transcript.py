"""Unit tests for transcript-aware silence removal (no ffmpeg/Whisper needed,
except the marked integration tests which reuse the committed fixture video
and a synthetic ffmpeg clip).

Covers: pause classification, kept-duration computation, keep-segment
building, transcript loading, and the CLI guards.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.remove_silence.transcript import (  # noqa: E402
    build_keep_segments,
    classify_pause,
    classify_silence,
    find_next_word,
    find_prev_word,
    kept_duration,
    load_transcript,
    punctuation_kind,
)


def _w(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


# ── punctuation_kind ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bonjour.", "sentence"),
        ("quoi ?", "sentence"),
        ("vite !", "sentence"),
        ("enfin…", "sentence"),
        ("mot...", "sentence"),  # last char is still a period
        ("oui,", "comma"),
        ("donc;", "comma"),
        ("voici:", "comma"),
        ("chercher", None),
        ("mot.\"", "sentence"),  # trailing quote stripped
        ("", None),
        ("   ", None),
    ],
)
def test_punctuation_kind(text, expected):
    assert punctuation_kind(text) == expected


# ── classify_pause ───────────────────────────────────────────────────────────

def test_sentence_end_short_silence():
    assert classify_pause("Bonjour.", 1.0, has_punctuation=True) == "sentence"


def test_sentence_end_long_silence_is_paragraph_when_threshold_set():
    assert classify_pause("Bonjour.", 2.0, has_punctuation=True, paragraph_threshold=1.5) == "paragraph"


def test_paragraph_threshold_zero_means_infinite():
    # Default: a sentence-end pause never counts as a paragraph.
    assert classify_pause("Bonjour.", 2.0, has_punctuation=True) == "sentence"
    assert classify_pause("Bonjour.", 30.0, has_punctuation=True) == "sentence"
    # ... and the duration fallback tops out at sentence too.
    assert classify_pause("plain words", 30.0, has_punctuation=False) == "sentence"


def test_sentence_end_exact_threshold_stays_sentence():
    assert classify_pause("Bonjour.", 1.5, has_punctuation=True, paragraph_threshold=1.5) == "sentence"


def test_comma():
    assert classify_pause("oui,", 1.2, has_punctuation=True) == "comma"


def test_plain_word_is_hesitation():
    assert classify_pause("chercher", 2.0, has_punctuation=True) == "hesitation"


@pytest.mark.parametrize(
    ("duration", "expected"),
    [(0.2, "hesitation"), (0.8, "sentence"), (1.5, "sentence"), (2.0, "paragraph")],
)
def test_fallback_by_duration_without_punctuation(duration, expected):
    words_without_punct = "no punctuation anywhere"
    assert (
        classify_pause(words_without_punct, duration, has_punctuation=False, paragraph_threshold=1.5)
        == expected
    )


def test_fallback_when_no_previous_word():
    assert classify_pause(None, 1.0, has_punctuation=True) == "sentence"
    assert classify_pause(None, 0.2, has_punctuation=True) == "hesitation"


# ── classify_silence (alignment tolerance) ───────────────────────────────────

def test_word_within_tolerance_drives_classification():
    words = [_w("chercher", 0.0, 1.0), _w("Bonjour.", 1.5, 1.95)]
    pause_type, prev, nxt = classify_silence(2.0, 3.0, words, tolerance=0.3)
    assert pause_type == "sentence"
    assert prev["text"] == "Bonjour."
    assert nxt is None


def test_word_beyond_tolerance_falls_back_to_duration():
    words = [_w("Bonjour.", 1.0, 1.60)]  # ends 0.40 s before the silence
    pause_type, prev, _ = classify_silence(2.0, 3.0, words, tolerance=0.3)
    assert prev is None
    assert pause_type == "sentence"  # 1.0 s original -> fallback band


def test_next_word_is_first_word_after_silence():
    words = [_w("salut.", 0.0, 1.9), _w("Toi", 3.1, 3.5), _w("aussi", 3.6, 4.0)]
    nxt = find_next_word(words, 3.0, tolerance=0.3)
    assert nxt["text"] == "Toi"


def test_prev_word_allows_slight_overlap_from_coarse_detection():
    # Detection granularity (~33 ms) can start the silence just before the
    # word actually ends.
    words = [_w("salut.", 0.0, 2.02)]
    prev = find_prev_word(words, 2.0, tolerance=0.3)
    assert prev["text"] == "salut."


# ── kept_duration ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("pause_type", "target"),
    [
        ("hesitation", 0.10),
        ("comma", 0.25),
        ("sentence", 0.45),
        ("paragraph", 0.90),
    ],
)
def test_kept_duration_defaults(pause_type, target):
    assert kept_duration(pause_type, 5.0) == pytest.approx(target)


def test_kept_duration_never_exceeds_original():
    assert kept_duration("sentence", 0.20) == pytest.approx(0.20)
    assert kept_duration("paragraph", 0.90) == pytest.approx(0.90)
    assert kept_duration("hesitation", 0.0) == pytest.approx(0.0)


# ── build_keep_segments ──────────────────────────────────────────────────────

def _words() -> list[dict]:
    return [
        _w("Salut.", 0.05, 1.90),   # sentence end
        _w("donc,", 3.05, 3.60),    # comma
        _w("on", 3.70, 3.90),
        _w("cherche", 4.00, 4.80),  # hesitation expected after
        _w("Fin.", 6.05, 7.80),     # sentence end before trailing silence
    ]


def test_internal_silences_keep_tail_adjacent_to_next_word():
    non_silent = [(0.0, 2.0), (3.0, 5.0), (6.0, 8.0)]
    keeps, reports = build_keep_segments(non_silent, 8.0, _words())
    assert len(reports) == 2
    first, second = reports
    assert (first["start"], first["end"]) == (2.0, 3.0)
    assert first["type"] == "sentence" and first["kept"] == pytest.approx(0.45)
    assert first["prev"] == "Salut." and first["next"] == "donc,"
    assert second["type"] == "hesitation" and second["kept"] == pytest.approx(0.10)
    # Tails end exactly at the next run, so they merge with it.
    assert keeps == [(0.0, 2.0), (2.55, 5.0), (5.90, 8.0)]


def test_leading_silence_classified_by_duration_and_keeps_tail():
    words = [_w("Salut.", 1.05, 2.90)]
    keeps, reports = build_keep_segments([(1.0, 3.0)], 3.0, words)
    assert len(reports) == 1
    rep = reports[0]
    assert (rep["start"], rep["end"]) == (0.0, 1.0)
    assert rep["type"] == "sentence"  # 1.0 s fallback, no previous word
    assert rep["prev"] == "" and rep["next"] == "Salut."
    assert rep["kept"] == pytest.approx(0.45)
    assert keeps == [(0.55, 3.0)]


def test_trailing_silence_keeps_head_adjacent_to_previous_word():
    words = [_w("Fin.", 0.0, 1.95)]
    keeps, reports = build_keep_segments([(0.0, 2.0)], 3.5, words)
    assert len(reports) == 1
    rep = reports[0]
    assert rep["type"] == "sentence"
    assert rep["prev"] == "Fin." and rep["next"] == ""
    assert rep["kept"] == pytest.approx(0.45)
    assert keeps == [(0.0, 2.45)]  # kept head merges with the speech run


def test_silence_shorter_than_target_is_kept_whole():
    words = [_w("on", 0.0, 0.95)]
    keeps, reports = build_keep_segments([(0.0, 1.0), (1.05, 2.0)], 2.0, words)
    assert reports[0]["original"] == pytest.approx(0.05)
    assert reports[0]["kept"] == pytest.approx(0.05)
    assert keeps == [(0.0, 2.0)]  # fully merged, nothing cut


def test_two_consecutive_silences_each_classified():
    # A tiny untranscribed blip between two silences: both gaps are still
    # classified from the nearest preceding word ("Vite ?").
    words = [_w("Vite ?", 0.0, 0.95), _w("stop.", 2.05, 2.90)]
    non_silent = [(0.0, 1.0), (1.1, 1.2), (2.0, 3.0)]
    keeps, reports = build_keep_segments(non_silent, 3.0, words)
    assert [r["type"] for r in reports] == ["sentence", "sentence"]
    assert reports[0]["kept"] == pytest.approx(0.10)  # 0.1 s gap kept whole
    assert reports[0]["prev"] == "Vite ?"
    assert reports[1]["kept"] == pytest.approx(0.45)
    assert reports[1]["prev"] == "Vite ?"  # 0.25 s away, within tolerance
    assert keeps == [(0.0, 1.2), (1.55, 3.0)]


def test_paragraph_end_keeps_longer_pause():
    words = [_w("Chapitre.", 0.0, 1.9)]
    keeps, reports = build_keep_segments([(0.0, 2.0), (4.0, 5.0)], 5.0, words, paragraph_threshold=1.5)
    assert reports[0]["type"] == "paragraph"  # 2.0 s original > 1.5 s
    assert reports[0]["kept"] == pytest.approx(0.90)
    assert keeps == [(0.0, 2.0), (3.10, 5.0)]


def test_paragraph_never_triggers_by_default():
    words = [_w("Chapitre.", 0.0, 1.9)]
    _, reports = build_keep_segments([(0.0, 2.0), (4.0, 5.0)], 5.0, words)
    assert reports[0]["type"] == "sentence"
    assert reports[0]["kept"] == pytest.approx(0.45)


# ── load_transcript ──────────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_json_with_words_prefers_word_level(tmp_path):
    payload = {
        "language": "fr",
        "words": [
            {"word": "Salut.", "start": 0.0, "end": 1.9},
            {"word": "Toi", "start": 3.1, "end": 3.5},
        ],
        "segments": [{"start": 0.0, "end": 3.5, "text": "Salut. Toi"}],
    }
    words = load_transcript(_write(tmp_path, "t.json", json.dumps(payload)))
    assert [(w["text"], w["start"], w["end"]) for w in words] == [
        ("Salut.", 0.0, 1.9),
        ("Toi", 3.1, 3.5),
    ]


def test_load_json_segments_only_falls_back_to_segment_level(tmp_path):
    payload = {
        "language": "fr",
        "text": "Salut. Toi",
        "segments": [
            {"start": 0.0, "end": 1.9, "text": "Salut."},
            {"start": 3.1, "end": 3.5, "text": "Toi"},
        ],
    }
    words = load_transcript(_write(tmp_path, "t.json", json.dumps(payload)))
    assert [w["text"] for w in words] == ["Salut.", "Toi"]


def test_load_json_top_level_array(tmp_path):
    payload = [{"word": "Go.", "start": 0.5, "end": 1.0}]
    words = load_transcript(_write(tmp_path, "t.json", json.dumps(payload)))
    assert words == [{"text": "Go.", "start": 0.5, "end": 1.0}]


def test_load_srt(tmp_path):
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\nBonjour le monde.\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nComment ça va ?\n"
    )
    words = load_transcript(_write(tmp_path, "t.srt", srt))
    assert [(w["text"], w["start"], w["end"]) for w in words] == [
        ("Bonjour le monde.", 0.0, 2.0),
        ("Comment ça va ?", 2.5, 4.0),
    ]


def test_load_vtt(tmp_path):
    vtt = (
        "WEBVTT\n\n00:00.000 --> 00:02.000\nSalut.\n\n"
        "00:03.000 --> 00:04.500\nToi aussi\n"
    )
    words = load_transcript(_write(tmp_path, "t.vtt", vtt))
    assert [w["text"] for w in words] == ["Salut.", "Toi aussi"]


def test_load_missing_file_errors_with_guidance(tmp_path):
    with pytest.raises(click.ClickException) as exc_info:
        load_transcript(tmp_path / "nope.json")
    assert "extract-transcript" in str(exc_info.value)


def test_load_invalid_json_errors(tmp_path):
    with pytest.raises(click.ClickException):
        load_transcript(_write(tmp_path, "t.json", "{not json"))


def test_load_plain_text_errors_with_guidance(tmp_path):
    with pytest.raises(click.ClickException) as exc_info:
        load_transcript(_write(tmp_path, "t.txt", "just some words, no timestamps\n"))
    assert "no word or segment timestamps" in str(exc_info.value)
    assert "extract-transcript" in str(exc_info.value)


# ── transcribe_to_json (mocked Whisper) ──────────────────────────────────────

class _W:
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class _S:
    def __init__(self, start: float, end: float, text: str, words: list):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


def test_transcribe_to_json_writes_word_level(test_video, tmp_path):
    from commands.extract_transcript.register import transcribe_to_json

    segments = [
        _S(0.0, 1.0, "Salut.", [_W("Salut.", 0.0, 1.0)]),
        _S(1.5, 2.0, "Toi", [_W("Toi", 1.5, 2.0)]),
    ]
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter(segments), MagicMock())
    out = tmp_path / "talk.json"
    with patch("faster_whisper.WhisperModel", return_value=mock_model):
        transcribe_to_json(str(test_video), str(out), language="fr", model_size="medium")

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["language"] == "fr"
    assert payload["words"] == [
        {"word": "Salut.", "start": 0.0, "end": 1.0},
        {"word": "Toi", "start": 1.5, "end": 2.0},
    ]
    assert payload["segments"] == [
        {"start": 0.0, "end": 1.0, "text": "Salut."},
        {"start": 1.5, "end": 2.0, "text": "Toi"},
    ]
    # Round-trip: the produced file is directly usable by load_transcript.
    assert [w["text"] for w in load_transcript(out)] == ["Salut.", "Toi"]


def test_transcribe_to_json_groq_path_writes_word_level(tmp_path):
    """Regression: the Groq branch must not hit UnboundLocalError on json."""
    import commands.extract_transcript.register as etr

    segments = [
        {"start": 0.0, "end": 1.0, "text": "Salut.",
         "words": [{"word": "Salut.", "start": 0.0, "end": 1.0}]},
    ]
    out = tmp_path / "talk.json"
    with patch.object(etr, "_fetch_groq_segments", return_value=segments):
        etr.transcribe_to_json("dummy.mp4", str(out), language="fr", use_groq=True)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["words"] == [{"word": "Salut.", "start": 0.0, "end": 1.0}]
    assert payload["segments"] == [{"start": 0.0, "end": 1.0, "text": "Salut."}]


# ── plan_transcript_cuts on the committed fixture (no Whisper) ───────────────

def test_plan_cuts_on_fixture_video(test_video, tmp_path):
    from commands.remove_silence.register import plan_transcript_cuts

    transcript = tmp_path / "talk.json"
    transcript.write_text(json.dumps({
        "language": "fr",
        "words": [
            {"word": "ceci", "start": 0.0, "end": 1.22},
            {"word": "test.", "start": 1.23, "end": 3.90},
            {"word": "vidéo", "start": 3.95, "end": 5.35},
        ],
    }), encoding="utf-8")

    original, keeps, reports = plan_transcript_cuts(
        str(test_video), -65.0, str(transcript)
    )
    assert original > 0
    assert reports, "expected at least one detected silence"
    for rep in reports:
        assert rep["type"] in {"hesitation", "comma", "sentence", "paragraph"}
        assert 0 <= rep["kept"] <= rep["original"]
    for start, end in keeps:
        assert 0 <= start < end <= original


# ── CLI guards ───────────────────────────────────────────────────────────────

def _remove_silence_cmd():
    from commands.remove_silence.register import register
    return register({}).click_command


def test_dry_run_requires_transcript(test_video):
    result = CliRunner().invoke(
        _remove_silence_cmd(), [str(test_video), "--dry-run"]
    )
    assert result.exit_code != 0
    assert "--dry-run requires --use-transcript" in result.output


def test_modal_with_transcript_rejected(test_video, tmp_path):
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({"words": []}), encoding="utf-8")
    result = CliRunner().invoke(
        _remove_silence_cmd(),
        [str(test_video), "--modal", "--use-transcript", str(transcript)],
    )
    assert result.exit_code != 0
    assert "local-only" in result.output


def test_dry_run_prints_table_and_writes_nothing(test_video, tmp_path):
    from commands.remove_silence.register import format_dry_run_table

    transcript = tmp_path / "talk.json"
    transcript.write_text(json.dumps({
        "language": "fr",
        "words": [{"word": "test.", "start": 0.0, "end": 1.0}],
    }), encoding="utf-8")
    result = CliRunner().invoke(
        _remove_silence_cmd(),
        [str(test_video), "--use-transcript", str(transcript), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "type" in result.output and "kept(s)" in result.output
    assert list(tmp_path.glob("*_nosilence*")) == []
    assert callable(format_dry_run_table)


# ── Rhythm config file (precedence + reset) ─────────────────────────────────

def _write_video_yaml(path: Path, mapping: dict) -> Path:
    import yaml

    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return path


def _patch_config_path(monkeypatch, tmp_path: Path) -> Path:
    # Patch BOTH bindings: config_file_path() resolves via common.core.paths
    # at call time, but save_tool_config() captured its own reference at
    # import time. Patching only one redirects reads but not writes
    # (depending on import order) — patching both is order-independent.
    target = tmp_path / "config.yaml"
    monkeypatch.setattr(
        "common.core.paths.get_tool_config_path",
        lambda tool_name, profile=None: target,
    )
    monkeypatch.setattr(
        "common.core.config.get_tool_config_path",
        lambda tool_name, profile=None: target,
    )
    return target


def test_rhythm_defaults_match_code_constants():
    from commands.remove_silence.config import RHYTHM_DEFAULTS
    from commands.remove_silence.transcript import (
        DEFAULT_CROSSFADE,
        DEFAULT_PARAGRAPH_THRESHOLD,
        DEFAULT_PAUSE_COMMA,
        DEFAULT_PAUSE_INLINE,
        DEFAULT_PAUSE_PARAGRAPH,
        DEFAULT_PAUSE_SENTENCE,
        DEFAULT_TOLERANCE,
    )

    assert RHYTHM_DEFAULTS == {
        "transcript_tolerance": DEFAULT_TOLERANCE,
        "paragraph_threshold": DEFAULT_PARAGRAPH_THRESHOLD,
        "pause_inline": DEFAULT_PAUSE_INLINE,
        "pause_comma": DEFAULT_PAUSE_COMMA,
        "pause_sentence": DEFAULT_PAUSE_SENTENCE,
        "pause_paragraph": DEFAULT_PAUSE_PARAGRAPH,
        "crossfade": DEFAULT_CROSSFADE,
    }
    assert RHYTHM_DEFAULTS["paragraph_threshold"] == 0


def test_load_missing_config_returns_defaults(tmp_path, monkeypatch):
    from commands.remove_silence.config import RHYTHM_DEFAULTS, load_rhythm_config

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path))
    assert load_rhythm_config() == RHYTHM_DEFAULTS


def test_load_reads_section_and_merges_over_defaults(tmp_path, monkeypatch):
    from commands.remove_silence.config import load_rhythm_config

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path))
    _write_video_yaml(tmp_path / "video.yaml", {
        "remove_silence": {"pause_inline": 0.5, "paragraph_threshold": 2.0},
        "other_tool": {"x": 1},
    })
    params = load_rhythm_config()
    assert params["pause_inline"] == pytest.approx(0.5)
    assert params["paragraph_threshold"] == pytest.approx(2.0)
    assert params["pause_comma"] == pytest.approx(0.25)  # default kept


def test_resolve_cli_overrides_config(tmp_path, monkeypatch):
    from commands.remove_silence.config import resolve_rhythm_params

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path))
    _write_video_yaml(tmp_path / "video.yaml", {
        "remove_silence": {"pause_inline": 0.5, "pause_comma": 0.3},
    })
    params = resolve_rhythm_params({"pause_inline": 0.05, "pause_sentence": None})
    assert params["pause_inline"] == pytest.approx(0.05)  # CLI wins
    assert params["pause_comma"] == pytest.approx(0.3)  # config wins over default
    assert params["pause_sentence"] == pytest.approx(0.45)  # default


@pytest.mark.parametrize("bad", ["fast", -0.5, True, [0.1]])
def test_invalid_config_value_raises(tmp_path, monkeypatch, bad):
    from commands.remove_silence.config import load_rhythm_config

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path))
    _write_video_yaml(tmp_path / "video.yaml", {"remove_silence": {"pause_inline": bad}})
    with pytest.raises(click.ClickException):
        load_rhythm_config()


def test_non_mapping_section_raises(tmp_path, monkeypatch):
    from commands.remove_silence.config import load_rhythm_config

    monkeypatch.setenv("FASTMARKET_CONFIG_DIR", str(tmp_path))
    _write_video_yaml(tmp_path / "video.yaml", {"remove_silence": "nope"})
    with pytest.raises(click.ClickException):
        load_rhythm_config()


def test_resolve_rejects_negative_cli():
    from commands.remove_silence.config import resolve_rhythm_params

    with pytest.raises(click.ClickException):
        resolve_rhythm_params({"pause_inline": -1.0})


def test_reset_writes_defaults_and_preserves_other_sections(tmp_path, monkeypatch):
    import yaml

    from commands.remove_silence.config import RHYTHM_DEFAULTS, load_rhythm_config, reset_rhythm_config

    target = _patch_config_path(monkeypatch, tmp_path)
    target.write_text(yaml.safe_dump({
        "remove_silence": {"pause_inline": 0.5},
        "other": {"keep": "me"},
    }), encoding="utf-8")

    assert reset_rhythm_config() == target
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert raw["remove_silence"] == RHYTHM_DEFAULTS
    assert raw["other"] == {"keep": "me"}
    assert load_rhythm_config() == RHYTHM_DEFAULTS


def test_reset_config_flag_needs_no_input_file(tmp_path, monkeypatch):
    import yaml

    from commands.remove_silence.register import register

    target = _patch_config_path(monkeypatch, tmp_path)
    result = CliRunner().invoke(register({}).click_command, ["--reset-config"])
    assert result.exit_code == 0, result.output
    assert "reset to defaults" in result.output
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert raw["remove_silence"]["pause_sentence"] == pytest.approx(0.45)
    assert raw["remove_silence"]["paragraph_threshold"] == 0


# ── End-to-end transcript cut on a synthetic clip ────────────────────────────

def _make_tone_silence_tone(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=128x72:d=5:r=10",
            "-f", "lavfi", "-i",
            "aevalsrc=sin(2*PI*440*t):d=2:s=44100[a1];"
            "anullsrc=r=44100:cl=mono:d=1[a2];"
            "aevalsrc=sin(2*PI*440*t):d=2:s=44100[a3];"
            "[a1][a2][a3]concat=n=3:v=0:a=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_end_to_end_transcript_cut_keeps_sentence_pause(tmp_path):
    from commands.remove_silence.register import remove_silence_transcript

    src = tmp_path / "src.mp4"
    _make_tone_silence_tone(src)
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({
        "language": "en",
        "words": [
            {"word": "Hello.", "start": 0.0, "end": 1.95},
            {"word": "World", "start": 3.05, "end": 4.90},
        ],
    }), encoding="utf-8")
    out = tmp_path / "out.mp4"
    _, orig, final = remove_silence_transcript(
        str(src), str(out), -65.0, str(transcript)
    )
    assert out.exists() and out.stat().st_size > 0
    # 1.0 s sentence pause shortened to ~0.45 s: final ≈ orig - 0.55.
    assert final < orig
    assert abs(final - (orig - 0.55)) <= 0.20


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
