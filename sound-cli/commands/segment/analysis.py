from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import click


def _require_ffmpeg() -> str:
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise click.ClickException("ffmpeg not found in PATH — required to extract/split audio.")
    return ffmpeg


def _extract_mono_wav(src: str, dst: str, sr: int = 16000) -> None:
    """Extract (or downmix) the audio track of SRC to a mono WAV at DST."""
    ffmpeg = _require_ffmpeg()
    subprocess.run(
        [ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", str(sr), dst],
        check=True,
        capture_output=True,
    )


# ── Transcription ─────────────────────────────────────────────────────────────


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def transcribe_whisperx(path: str, model_size: str, language: str) -> dict:
    """Local transcription with word-level timestamps via whisperx + alignment."""
    import whisperx

    device = _device()
    audio = whisperx.load_audio(path)
    model = whisperx.load_model(model_size, device=device, compute_type="int8")
    lang = None if language in ("auto", "", None) else language
    result = model.transcribe(audio, batch_size=16, language=lang)
    detected = result.get("language", "en")

    align_model, metadata = whisperx.load_align_model(
        language_code=detected, device=device
    )
    result = whisperx.align(
        result["segments"], align_model, metadata, audio, device,
        return_char_alignments=False,
    )

    words: list[dict] = []
    segments: list[dict] = []
    for seg in result.get("segments", []):
        seg_words = [
            {"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
            for w in seg.get("words", [])
            if w.get("word", "").strip()
        ]
        words.extend(seg_words)
        text = seg.get("text", "").strip()
        if text:
            segments.append(
                {"start": float(seg["start"]), "end": float(seg["end"]), "text": text}
            )
    return {"language": detected, "words": words, "segments": segments}


def transcribe_faster_whisper(path: str, model_size: str, language: str) -> dict:
    """Local transcription with word-level timestamps via faster-whisper."""
    from faster_whisper import WhisperModel

    device = _device()
    model = WhisperModel(model_size, device=device, compute_type="int8")
    lang = None if language in ("auto", "", None) else language

    segments_iter, info = model.transcribe(
        path,
        word_timestamps=True,
        language=lang,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    words: list[dict] = []
    segments: list[dict] = []
    for seg in segments_iter:
        seg_words = [
            {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
        words.extend(seg_words)
        text = (seg.text or "").strip()
        if text:
            segments.append(
                {"start": float(seg.start), "end": float(seg.end), "text": text}
            )
    detected = getattr(info, "language", "en") or "en"
    return {"language": detected, "words": words, "segments": segments}


def transcribe_local(path: str, model_size: str, language: str) -> dict:
    """Local word-aligned transcription. Uses whisperx when available, else faster-whisper."""
    try:
        return transcribe_whisperx(path, model_size, language)
    except ImportError:
        return transcribe_faster_whisper(path, model_size, language)


def transcribe_groq(path: str, language: str) -> dict:
    """Transcription via Groq's hosted whisper-large-v3 API (word-level)."""
    import os
    import requests

    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).parent.parent.parent.parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        pass

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise click.ClickException(
            "GROQ_API_KEY environment variable not set (required for --engine groq)."
        )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as _tmp:
        tmp_audio = _tmp.name
    try:
        _extract_mono_wav(path, tmp_audio, sr=16000)
        form_data = [
            ("model", "whisper-large-v3"),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if language and language != "auto":
            form_data.append(("language", language))
        with open(tmp_audio, "rb") as f:
            resp = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (os.path.basename(tmp_audio), f, "audio/mpeg")},
                data=form_data,
                timeout=300,
            )
        resp.raise_for_status()
        result = resp.json()
    finally:
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass

    flat_words = result.get("words", [])
    raw_segments = result.get("segments", [])

    words: list[dict] = []
    segments: list[dict] = []
    word_idx = 0
    for seg in raw_segments:
        seg_words = []
        while word_idx < len(flat_words):
            w = flat_words[word_idx]
            if w["start"] < seg["end"] - 0.001:
                seg_words.append(
                    {"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
                )
                word_idx += 1
            else:
                break
        words.extend(seg_words)
        text = seg.get("text", "").strip()
        if text:
            segments.append(
                {"start": float(seg["start"]), "end": float(seg["end"]), "text": text}
            )
    if word_idx < len(flat_words):
        remaining = flat_words[word_idx:]
        text = " ".join(w["word"].strip() for w in remaining)
        if text:
            segments.append(
                {
                    "start": float(remaining[0]["start"]),
                    "end": float(remaining[-1]["end"]),
                    "text": text,
                }
            )
    return {"language": result.get("language", "en"), "words": words, "segments": segments}


def transcribe(path: str, engine: str, model_size: str, language: str) -> dict:
    if engine == "groq":
        return transcribe_groq(path, language)
    return transcribe_local(path, model_size, language)


# ── Segmentation ──────────────────────────────────────────────────────────────


def _split_unit_by_words(
    words: list[dict], start: float, end: float, text: str
) -> tuple[tuple[float, float, str], tuple[float, float, str]]:
    """Split one over-long unit at the most natural word boundary."""
    ws = [w for w in words if start - 1e-3 <= w["start"] and w["end"] <= end + 1e-3]
    if len(ws) < 2:
        mid = (start + end) / 2
        return (start, mid, text), (mid, end, text)

    mid = (start + end) / 2
    best_i, best_score = 1, -1e9
    for i in range(1, len(ws)):
        gap = ws[i]["start"] - ws[i - 1]["end"]
        boundary_t = ws[i]["start"]
        score = gap - abs(boundary_t - mid) * 0.1
        if score > best_score:
            best_score, best_i = score, i

    p1, p2 = ws[:best_i], ws[best_i:]
    t1 = " ".join(w["word"] for w in p1).strip()
    t2 = " ".join(w["word"] for w in p2).strip()
    return (
        (p1[0]["start"], p1[-1]["end"], t1),
        (p2[0]["start"], p2[-1]["end"], t2),
    )


def segment_words(
    words: list[dict],
    segments: list[dict],
    min_seg: float,
    max_seg: float,
    silence: float,
) -> list[dict]:
    """Group transcript words into timed scenes.

    Boundaries prefer natural pauses (gaps > silence) and sentence ends, then
    enforce a soft min duration (merge short scenes) and a hard max duration
    (split long scenes at the largest internal silence).
    """
    units = [
        (s["start"], s["end"], s["text"])
        for s in segments
        if str(s.get("text", "")).strip()
    ]
    if not units and words:
        units = [(words[0]["start"], words[-1]["end"], " ".join(w["word"] for w in words))]

    # 1. Split over-long sentence units at the largest internal silence.
    split_units: list[tuple[float, float, str]] = []
    for start, end, text in units:
        if (end - start) > max_seg and len(words) > 1:
            split_units.extend(_split_unit_by_words(words, start, end, text))
        else:
            split_units.append((start, end, text))

    # 2. Merge short units to reach the target min duration (skip across pauses
    #    only when the merged result stays within a reasonable tolerance).
    merged: list[tuple[float, float, str]] = []
    for start, end, text in split_units:
        if merged and (merged[-1][1] - merged[-1][0]) < min_seg:
            if (end - merged[-1][0]) <= max_seg * 1.5:
                ps, pe, pt = merged[-1]
                merged[-1] = (ps, end, (pt + " " + text).strip())
                continue
        merged.append((start, end, text))

    # 3. Final split of anything still over max (e.g. a long pause-less unit).
    final: list[tuple[float, float, str]] = []
    for start, end, text in merged:
        while (end - start) > max_seg:
            part1, part2 = _split_unit_by_words(words, start, end, text)
            final.append(part1)
            start, end, text = part2
        final.append((start, end, text))

    return [
        {"start": round(s, 2), "end": round(e, 2), "text": t.strip()}
        for s, e, t in final
        if t.strip()
    ]


# ── Output writing ────────────────────────────────────────────────────────────


def write_segments(
    source: str,
    manifest: dict,
    segments: list[dict],
    output_dir: Path,
    sr: int = 44100,
) -> dict:
    """Write segments.json, per-segment WAVs and script.txt. Returns the manifest."""
    output_dir = Path(output_dir)
    segs_dir = output_dir / "segments"
    segs_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = _require_ffmpeg()
    out_segments = []
    for i, seg in enumerate(segments):
        seg_wav = segs_dir / f"seg_{i:03d}.wav"
        subprocess.run(
            [
                ffmpeg, "-y",
                "-ss", f"{seg['start']:.3f}",
                "-to", f"{seg['end']:.3f}",
                "-i", source,
                "-vn", "-ac", "1", "-ar", str(sr),
                str(seg_wav),
            ],
            check=True,
            capture_output=True,
        )
        out_segments.append(
            {
                "index": i,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "audio": f"segments/seg_{i:03d}.wav",
            }
        )

    script_text = "\n\n".join(s["text"] for s in out_segments)
    (output_dir / "script.txt").write_text(script_text, encoding="utf-8")

    result = {
        "source": source,
        "engine": manifest.get("engine"),
        "model": manifest.get("model"),
        "language": manifest.get("language"),
        "segment_count": len(out_segments),
        "segments_file": str(output_dir / "segments.json"),
        "script_file": str(output_dir / "script.txt"),
        "segments_dir": str(segs_dir),
        "segments": out_segments,
    }
    (output_dir / "segments.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
