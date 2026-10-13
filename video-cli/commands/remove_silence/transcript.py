"""Transcript-aware pause classification for ``remove-silence`` (local only).

A detected silence is treated as punctuation: the word that ends right
before it tells us whether the pause ends a sentence, follows a comma,
or is a mid-sentence hesitation. Each kind keeps a different target
duration (never longer than the original silence).

This module is pure Python (no ffmpeg / MoviePy) so it can be unit
tested without media files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import click


# ── Pause types ─────────────────────────────────────────────────────────────

HESITATION = "hesitation"
COMMA = "comma"
SENTENCE = "sentence"
PARAGRAPH = "paragraph"
SPEECH = "speech"

# ── Canonical rhythm defaults (single source of truth) ──────────────────────
# Also used for the `remove_silence` section of the video config file and for
# `video remove-silence --reset-config`. CLI options override the config
# file, which overrides these values.

DEFAULT_TOLERANCE = 0.3
# 0 means infinite: the threshold check is ignored and a sentence-end pause
# never counts as a paragraph (paragraph keeps only apply when explicitly set).
DEFAULT_PARAGRAPH_THRESHOLD = 0.0
DEFAULT_PAUSE_INLINE = 0.10
DEFAULT_PAUSE_COMMA = 0.25
DEFAULT_PAUSE_SENTENCE = 0.45
DEFAULT_PAUSE_PARAGRAPH = 0.90
DEFAULT_CROSSFADE = 0.008
DEFAULT_HESITATION_MAX = 0.8

_SENTENCE_END = {".", "!", "?", "…"}
_COMMA_END = {",", ";", ":"}
# Closing quotes/brackets stripped before reading the final punctuation, so
# e.g. 'word."' still counts as a sentence end.
_TRAILING_STRIP = "\"'”’)}]»›"


def punctuation_kind(text: str) -> str | None:
    """Return ``"sentence"``, ``"comma"`` or None for a word/segment text."""
    cleaned = (text or "").strip().rstrip(_TRAILING_STRIP).rstrip()
    if not cleaned:
        return None
    last = cleaned[-1]
    if last in _SENTENCE_END:
        return SENTENCE
    if last in _COMMA_END:
        return COMMA
    return None


# ── Transcript loading ──────────────────────────────────────────────────────

_HOW_TO_GET_TRANSCRIPT = (
    "Generate a timestamped transcript with one of:\n"
    "  video extract-transcript INPUT -f json   (word-level, recommended)\n"
    "  video extract-transcript INPUT -f srt    (segment-level)\n"
    "  sound transcribe INPUT -F json -o out.json  (segment-level)"
)


def _coerce_word(entry: dict) -> dict | None:
    """Normalize one word entry to {text, start, end}; None when unusable."""
    if not isinstance(entry, dict):
        return None
    text = entry.get("word", entry.get("text", ""))
    try:
        start = float(entry.get("start"))
        end = float(entry.get("end"))
    except (TypeError, ValueError):
        return None
    text = str(text or "").strip()
    if not text or end <= start:
        return None
    return {"text": text, "start": start, "end": end}


def _coerce_segment(entry: dict) -> dict | None:
    """Normalize one segment entry to {start, end, text}; None when unusable."""
    if not isinstance(entry, dict):
        return None
    try:
        start = float(entry.get("start"))
        end = float(entry.get("end"))
    except (TypeError, ValueError):
        return None
    text = str(entry.get("text", "") or "").strip()
    if not text or end <= start:
        return None
    return {"start": start, "end": end, "text": text}


_SRT_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
)


def _srt_part_to_seconds(h: str | None, m: str, s: str, frac: str) -> float:
    hours = int(h) if h else 0
    return hours * 3600 + int(m) * 60 + int(s) + int(frac) / (10 ** len(frac))


def _parse_subtitles(content: str) -> list[dict]:
    """Parse SRT or WebVTT content into segment dicts."""
    segments: list[dict] = []
    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_start is not None and current_lines:
            text = " ".join(current_lines).strip()
            if text and current_end > current_start:
                segments.append(
                    {"start": current_start, "end": current_end, "text": text}
                )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        match = _SRT_RE.search(line)
        if match:
            flush()
            current_lines = []
            current_start = _srt_part_to_seconds(*match.groups()[:4])
            current_end = _srt_part_to_seconds(*match.groups()[4:])
        elif not line or line == "WEBVTT" or line.startswith("NOTE"):
            flush()
            current_start = None
            current_lines = []
        elif line.isdigit() and current_start is None:
            continue  # SRT cue number
        elif current_start is not None:
            current_lines.append(line)
    flush()
    return segments


def load_transcript(path: str | Path) -> list[dict]:
    """Load a timestamped transcript as a flat word list [{text, start, end}].

    Accepted inputs (word-level preferred):
      - JSON object with a ``words`` array (word-level), e.g. the output of
        ``video extract-transcript -f json``;
      - JSON object with a ``segments`` array or a top-level JSON array
        (segment-level; each segment becomes one pseudo-word);
      - ``.srt`` / ``.vtt`` subtitle files (segment-level).

    Raises a ClickException with guidance when the file is unreadable
    or carries no timestamps.
    """
    src = Path(path)
    if not src.exists():
        raise click.ClickException(
            f"Transcript file not found: {src}\n{_HOW_TO_GET_TRANSCRIPT}"
        )
    try:
        content = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(
            f"Cannot read transcript file {src}: {exc}\n{_HOW_TO_GET_TRANSCRIPT}"
        ) from exc

    suffix = src.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"Transcript {src} is not valid JSON ({exc}).\n"
                f"{_HOW_TO_GET_TRANSCRIPT}"
            ) from exc
        return _words_from_json(data, src)
    if suffix in {".srt", ".vtt"}:
        segments = _parse_subtitles(content)
        return _words_from_segments(segments, src)

    # Unknown extension: sniff the content (JSON vs subtitles).
    stripped = content.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            return _words_from_json(json.loads(content), src)
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"Transcript {src} is not valid JSON ({exc}).\n"
                f"{_HOW_TO_GET_TRANSCRIPT}"
            ) from exc
    segments = _parse_subtitles(content)
    return _words_from_segments(segments, src)


def _words_from_json(data, src: Path) -> list[dict]:
    words: list[dict] = []
    segments: list[dict] = []
    if isinstance(data, dict):
        raw_words = data.get("words") or []
        raw_segments = data.get("segments") or []
    elif isinstance(data, list):
        # Top-level array: treat word-like entries as words, the rest as segments.
        raw_words = [e for e in data if _looks_like_word(e)]
        raw_segments = [e for e in data if not _looks_like_word(e)] if not raw_words else []
    else:
        raw_words, raw_segments = [], []

    for entry in raw_words if isinstance(raw_words, list) else []:
        word = _coerce_word(entry)
        if word:
            words.append(word)
    # Some producers nest word lists inside segments (Groq verbose_json).
    seg_list = raw_segments if isinstance(raw_segments, list) else []
    for entry in seg_list:
        if isinstance(entry, dict):
            for nested in entry.get("words") or []:
                word = _coerce_word(nested)
                if word:
                    words.append(word)
    if words:
        words.sort(key=lambda w: (w["start"], w["end"]))
        return words

    for entry in seg_list:
        segment = _coerce_segment(entry)
        if segment:
            segments.append(segment)
    return _words_from_segments(segments, src)


def _looks_like_word(entry) -> bool:
    return isinstance(entry, dict) and "start" in entry and (
        "word" in entry or "text" in entry
    )


def _words_from_segments(segments: list[dict], src: Path) -> list[dict]:
    if not segments:
        raise click.ClickException(
            f"Transcript {src} contains no word or segment timestamps.\n"
            f"{_HOW_TO_GET_TRANSCRIPT}"
        )
    # Segment-level fallback: one pseudo-word per segment, so the same
    # punctuation/duration logic applies to the segment end.
    return [
        {"text": seg["text"], "start": seg["start"], "end": seg["end"]}
        for seg in segments
    ]


# ── Classification ──────────────────────────────────────────────────────────

def find_prev_word(
    words: list[dict], silence_start: float, tolerance: float
) -> dict | None:
    """Last word ending close to the silence start (within tolerance)."""
    best: dict | None = None
    for word in words:
        if word["end"] <= silence_start + tolerance:
            if best is None or word["end"] >= best["end"]:
                best = word
    if best is not None and (silence_start - best["end"]) <= tolerance:
        return best
    return None


def find_next_word(
    words: list[dict], silence_end: float, tolerance: float
) -> dict | None:
    """First word starting close to (or after) the silence end."""
    best: dict | None = None
    for word in words:
        if word["start"] >= silence_end - tolerance:
            if best is None or word["start"] <= best["start"]:
                best = word
    return best


def classify_pause(
    prev_text: str | None,
    original_duration: float,
    *,
    has_punctuation: bool,
    paragraph_threshold: float = DEFAULT_PARAGRAPH_THRESHOLD,
    hesitation_max: float = DEFAULT_HESITATION_MAX,
) -> str:
    """Classify one silence as hesitation / comma / sentence / paragraph.

    A paragraph_threshold of 0 means infinite: the check is ignored and a
    sentence-end pause never counts as a paragraph.
    """
    limit = paragraph_threshold if paragraph_threshold > 0 else float("inf")
    if prev_text and has_punctuation:
        kind = punctuation_kind(prev_text)
        if kind == SENTENCE:
            return PARAGRAPH if original_duration > limit else SENTENCE
        if kind == COMMA:
            return COMMA
        return HESITATION
    # Fallback when the transcript has no punctuation or no word could
    # be aligned to this silence: classify by original duration only.
    if original_duration < hesitation_max:
        return HESITATION
    if original_duration <= limit:
        return SENTENCE
    return PARAGRAPH


def classify_silence(
    silence_start: float,
    silence_end: float,
    words: list[dict],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    paragraph_threshold: float = DEFAULT_PARAGRAPH_THRESHOLD,
    hesitation_max: float = DEFAULT_HESITATION_MAX,
) -> tuple[str, dict | None, dict | None]:
    """Classify one silence; returns (pause_type, prev_word, next_word)."""
    has_punctuation = any(
        punctuation_kind(w["text"]) is not None for w in words if w["text"]
    )
    prev_word = find_prev_word(words, silence_start, tolerance)
    next_word = find_next_word(words, silence_end, tolerance)
    pause_type = classify_pause(
        prev_word["text"] if prev_word else None,
        silence_end - silence_start,
        has_punctuation=has_punctuation,
        paragraph_threshold=paragraph_threshold,
        hesitation_max=hesitation_max,
    )
    return pause_type, prev_word, next_word


# ── Kept-duration computation ───────────────────────────────────────────────

def kept_duration(
    pause_type: str,
    original_duration: float,
    *,
    pause_inline: float = DEFAULT_PAUSE_INLINE,
    pause_comma: float = DEFAULT_PAUSE_COMMA,
    pause_sentence: float = DEFAULT_PAUSE_SENTENCE,
    pause_paragraph: float = DEFAULT_PAUSE_PARAGRAPH,
) -> float:
    """Seconds to keep; never longer than the original silence."""
    targets = {
        HESITATION: pause_inline,
        COMMA: pause_comma,
        SENTENCE: pause_sentence,
        PARAGRAPH: pause_paragraph,
    }
    target = targets.get(pause_type, pause_inline)
    return min(max(original_duration, 0.0), max(target, 0.0))


# ── Keep-segment computation ────────────────────────────────────────────────

def build_keep_segments(
    non_silent: list[tuple[float, float]],
    duration: float,
    words: list[dict],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    paragraph_threshold: float = DEFAULT_PARAGRAPH_THRESHOLD,
    hesitation_max: float = DEFAULT_HESITATION_MAX,
    pause_inline: float = DEFAULT_PAUSE_INLINE,
    pause_comma: float = DEFAULT_PAUSE_COMMA,
    pause_sentence: float = DEFAULT_PAUSE_SENTENCE,
    pause_paragraph: float = DEFAULT_PAUSE_PARAGRAPH,
) -> tuple[list[tuple[float, float]], list[dict]]:
    """Compute the (start, end) intervals to keep for transcript-aware cuts.

    Speech runs are kept whole; each silence keeps a target tail adjacent
    to the NEXT word (breath before a sentence), except the trailing
    silence whose head is kept adjacent to the previous word.
    Returns (merged_keep_intervals, silence_reports) where each report
    holds start/end/original/type/kept/prev/next for --dry-run.
    """
    keeps: list[tuple[float, float]] = []
    reports: list[dict] = []

    def _silence_report(start: float, end: float, keep_tail: bool) -> None:
        original = end - start
        pause_type, prev_word, next_word = classify_silence(
            start, end, words,
            tolerance=tolerance,
            paragraph_threshold=paragraph_threshold,
            hesitation_max=hesitation_max,
        )
        keep = kept_duration(
            pause_type, original,
            pause_inline=pause_inline,
            pause_comma=pause_comma,
            pause_sentence=pause_sentence,
            pause_paragraph=pause_paragraph,
        )
        reports.append({
            "start": start,
            "end": end,
            "original": original,
            "type": pause_type,
            "kept": keep,
            "prev": prev_word["text"] if prev_word else "",
            "next": next_word["text"] if next_word else "",
        })
        if keep > 0:
            if keep_tail:
                keeps.append((end - keep, end))
            else:
                keeps.append((start, start + keep))

    if non_silent and non_silent[0][0] > 0:
        _silence_report(0.0, non_silent[0][0], keep_tail=True)

    for i, (start, end) in enumerate(non_silent):
        keeps.append((start, end))
        if i + 1 < len(non_silent):
            next_start = non_silent[i + 1][0]
            if next_start > end:
                _silence_report(end, next_start, keep_tail=True)

    if non_silent and non_silent[-1][1] < duration:
        _silence_report(non_silent[-1][1], duration, keep_tail=False)

    # Merge touching intervals (silence tails end exactly at the next run).
    merged: list[tuple[float, float]] = []
    for start, end in sorted(keeps):
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged, reports
