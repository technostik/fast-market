"""
Regression tests for the video processing pipeline steps 0-2.

Steps covered:
  0  remove silence     (remove_silence_simple)
  1  transcribe to ASS  (generate_karaoke_ass)
  2  burn subtitles     (burn_ass_subtitles)

Steps 3 (LLM title/description) and 4 (YouTube upload) are excluded — they
require live credentials and produce non-deterministic output.

Test assets (all committed to git):
  tests/fixtures/publish/test_clip.mkv          6 s source video
  tests/fixtures/publish/golden/test_clip.ass   reference ASS transcript
  tests/fixtures/publish/golden/durations.json  reference durations per step

To regenerate golden fixtures after an intentional change:
  cd video-cli
  pytest tests/test_publish_regression.py --generate-golden
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PUBLISH_FIXTURES = Path(__file__).parent / "fixtures" / "publish"
GOLDEN_DIR = PUBLISH_FIXTURES / "golden"
GOLDEN_ASS = GOLDEN_DIR / "test_clip.ass"
GOLDEN_DURATIONS = GOLDEN_DIR / "durations.json"

# ── One video frame at 30 fps — the tightest meaningful tolerance for encoded
#    output durations.  The silence-detection granularity is also ~33 ms.
FRAME = 1 / 30


# ── Fixed Whisper segments extracted from the golden ASS  ────────────────────
#
# Mocking WhisperModel makes the ASS-generation test fully deterministic:
# we control the exact timing fed into generate_karaoke_ass() and can compare
# the output byte-for-byte against the golden file.
#
# Timing is reverse-engineered from golden/test_clip.ass:
#   Dialogue line 1 (0.00–3.94 s): {\k122}ceci {\k19}est {\k16}un {\k41}test
#                                   {\k31}de {\k48}vidéo {\k90}ceci {\k23}est
#   Dialogue line 2 (3.94–5.38 s): {\k23}un {\k58}test {\k37}de {\k24}vidéo
#
# Centiseconds → seconds: k122 → 1.22 s, k19 → 0.19 s, …

class _W:
    """Minimal word-timing object matching faster_whisper's Word namedtuple."""
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class _S:
    """Minimal segment object matching faster_whisper's Segment namedtuple."""
    def __init__(self, start: float, end: float, text: str, words: list):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


# Word timings: start = cumulative centisecond sum, end = start + k/100 + 1e-3
# The 1ms nudge on end prevents int((end-start)*100) from flooring down due to
# IEEE-754 subtraction (e.g. 1.41 - 1.22 → 0.18999... → int → 18, not 19).
# Verified: int((end-start)*100) == k for every word below.
_SEG1_WORDS = [
    _W("ceci",  0.00,  1.221),   # k=122
    _W("est",   1.22,  1.411),   # k=19
    _W("un",    1.41,  1.571),   # k=16
    _W("test",  1.57,  1.981),   # k=41
    _W("de",    1.98,  2.291),   # k=31
    _W("vidéo", 2.29,  2.771),   # k=48
    _W("ceci",  2.77,  3.671),   # k=90
    _W("est",   3.67,  3.901),   # k=23
]
_SEG2_WORDS = [
    _W("un",    3.94,  4.171),   # k=23
    _W("test",  4.17,  4.751),   # k=58
    _W("de",    4.75,  5.121),   # k=37
    _W("vidéo", 5.12,  5.361),   # k=24
]
FIXED_SEGMENTS = [
    _S(0.00, 3.94, "ceci est un test de vidéo ceci est", _SEG1_WORDS),
    _S(3.94, 5.38, "un test de vidéo",                  _SEG2_WORDS),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        text=True,
    )
    return float(json.loads(out)["format"]["duration"])


def _is_valid_video(path: Path) -> bool:
    return subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_format", str(path)],
        capture_output=True,
    ).returncode == 0


def _dialogue_lines(ass: str) -> list[str]:
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


# ── Step 1: Transcription ────────────────────────────────────────────────────

class TestTranscriptionRegression:
    """
    Exact regression for the ASS karaoke generation code.

    Whisper is non-deterministic between runs (beam-search ordering varies),
    so we mock it with the fixed segments from the golden run.  This makes
    generate_karaoke_ass() fully deterministic and lets us compare byte-for-byte.

    What this catches after a refactoring:
      - changed timing arithmetic (ms_to_ass_time, build_tagged centiseconds)
      - changed line-splitting logic (split_long_line threshold, grouping)
      - changed ASS header (colours, font size, alignment, margin)
      - changed Dialogue format string
    """

    def _run_with_fixed_segments(self, test_video: Path, tmp_path: Path) -> Path:
        from commands.extract_transcript.register import generate_karaoke_ass

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(FIXED_SEGMENTS), MagicMock())

        out = tmp_path / "output.ass"
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            generate_karaoke_ass(str(test_video), str(out), language="fr", model_size="medium")
        return out

    def test_golden_fixture_exists(self):
        assert GOLDEN_ASS.exists(), (
            f"Golden ASS missing: {GOLDEN_ASS}\n"
            "Regenerate with:  pytest tests/test_publish_regression.py --generate-golden"
        )

    def test_exact_ass_output_matches_golden(self, test_video, tmp_path):
        """ASS output must be byte-for-byte identical to the committed golden."""
        out = self._run_with_fixed_segments(test_video, tmp_path)
        actual = out.read_text(encoding="utf-8")
        golden = GOLDEN_ASS.read_text(encoding="utf-8")
        assert actual == golden, (
            "ASS output differs from golden.\n"
            f"Dialogue lines produced:\n" +
            "\n".join(_dialogue_lines(actual)) +
            "\nExpected:\n" +
            "\n".join(_dialogue_lines(golden)) +
            "\nIf the change is intentional: pytest --generate-golden"
        )

    def test_ass_header_intact(self, test_video, tmp_path):
        """ASS sections and style fields must be present and well-formed."""
        out = self._run_with_fixed_segments(test_video, tmp_path)
        content = out.read_text(encoding="utf-8")

        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content
        assert "Style: Default,Arial,96," in content
        assert "&H0000FF00" in content   # primary green
        assert "&H00FFFFFF" in content   # secondary white

        for line in _dialogue_lines(content):
            fields = line.split(",", 9)
            assert len(fields) == 10, f"Malformed Dialogue line: {line}"
            assert re.search(r"\{\\k\d+\}", fields[9]), f"No karaoke tag in: {line}"


# ── Step 0: Silence removal ──────────────────────────────────────────────────

class TestSilenceRemoval:
    """
    Exact regression for remove_silence_simple.

    The bug that triggered this test suite: a refactoring changed the
    output duration by < 1 s, which silently shifted audio sync.
    Tolerance is set to one video frame (≈33 ms) to catch any such drift.
    """

    def _run(self, test_video: Path, tmp_path: Path):
        from commands.remove_silence.register import remove_silence_simple
        out = tmp_path / "nosilence.mp4"
        _, orig, final = remove_silence_simple(str(test_video), str(out), threshold=-65.0)
        return out, orig, final

    def test_produces_valid_video(self, test_video, tmp_path):
        out, _, _ = self._run(test_video, tmp_path)
        assert out.exists() and out.stat().st_size > 0
        assert _is_valid_video(out)

    def test_reported_duration_matches_golden(self, test_video, tmp_path):
        """Reported duration (sum of non-silent segments) must match golden within 1 frame."""
        ref = json.loads(GOLDEN_DURATIONS.read_text())["silence_removal"]["reported_duration"]
        _, _, final = self._run(test_video, tmp_path)
        assert abs(final - ref) <= FRAME, (
            f"Reported duration {final:.4f}s deviates from golden {ref:.4f}s "
            f"by {abs(final-ref)*1000:.1f} ms  (limit: {FRAME*1000:.1f} ms = 1 frame)"
        )

    def test_probed_duration_matches_golden(self, test_video, tmp_path):
        """Container duration (ffprobe) must match golden within 1 frame."""
        ref = json.loads(GOLDEN_DURATIONS.read_text())["silence_removal"]["probed_duration"]
        out, _, _ = self._run(test_video, tmp_path)
        actual = _probe_duration(out)
        assert abs(actual - ref) <= FRAME, (
            f"Probed duration {actual:.4f}s deviates from golden {ref:.4f}s "
            f"by {abs(actual-ref)*1000:.1f} ms  (limit: {FRAME*1000:.1f} ms = 1 frame)"
        )

    def test_output_shorter_than_source(self, test_video, tmp_path):
        ref_src = json.loads(GOLDEN_DURATIONS.read_text())["source"]["duration"]
        _, orig, final = self._run(test_video, tmp_path)
        assert final < orig
        assert abs(orig - ref_src) <= FRAME, (
            f"Source duration {orig:.4f}s differs from golden {ref_src:.4f}s — "
            "test video may have changed"
        )


# ── Step 2: Subtitle burning ─────────────────────────────────────────────────

class TestSubtitleBurning:
    """
    Regression for burn_ass_subtitles.

    Uses the committed golden ASS so subtitle content is known-good and
    the only variable is the ffmpeg encoding step.
    """

    def _run(self, test_video: Path, tmp_path: Path) -> Path:
        from commands.burn_subtitles.register import burn_ass_subtitles
        out = tmp_path / "subtitled.mp4"
        burn_ass_subtitles(str(test_video), str(GOLDEN_ASS), str(out))
        return out

    def test_produces_valid_video(self, test_video, tmp_path):
        out = self._run(test_video, tmp_path)
        assert out.exists() and out.stat().st_size > 0
        assert _is_valid_video(out)

    def test_probed_duration_matches_golden(self, test_video, tmp_path):
        """Container duration must match golden within 1 frame."""
        ref = json.loads(GOLDEN_DURATIONS.read_text())["subtitle_burn"]["probed_duration"]
        out = self._run(test_video, tmp_path)
        actual = _probe_duration(out)
        assert abs(actual - ref) <= FRAME, (
            f"Subtitled duration {actual:.4f}s deviates from golden {ref:.4f}s "
            f"by {abs(actual-ref)*1000:.1f} ms  (limit: {FRAME*1000:.1f} ms = 1 frame)"
        )
