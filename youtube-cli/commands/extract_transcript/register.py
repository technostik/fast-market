from __future__ import annotations

import re
from pathlib import Path

import click

from commands.base import CommandManifest

# ── ASS helpers ───────────────────────────────────────────────────────────────

def ms_to_ass_time(ms: int) -> str:
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    cs = (ms % 1000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}:{cs:02d}"


def generate_karaoke_ass(
    input_path: str,
    output_ass_path: str,
    language: str = "fr",
    model_size: str = "medium",
    subtitle_size: int = 96,
    max_line_chars: int = 35,
    progress_cb=None,
) -> None:
    """
    Transcribe video to ASS karaoke subtitles with word-level green/white highlighting.
    Green = primary (being read), White = secondary (pre-read), middle-centered.
    If progress_cb is given it receives (current_pct, 100).
    """
    from faster_whisper import WhisperModel
    import subprocess, json

    # best-effort total duration for percentage
    total_dur = None
    try:
        dur_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", input_path]
        dur_out = subprocess.check_output(dur_cmd, text=True)
        total_dur = float(json.loads(dur_out)["format"]["duration"])
    except Exception:
        pass

    lang = language if language != "auto" else None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, _ = model.transcribe(input_path, word_timestamps=True, language=lang)

    result_segments = []
    for seg in segments_iter:
        word_list = [
            {"word": w.word.strip(), "start": w.start, "end": w.end}
            for w in (seg.words or [])
        ]
        result_segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": word_list,
        })

    primary_color = "&H0000FF00"   # green — word being read
    secondary_color = "&H00FFFFFF" # white — words not yet read
    outline_color = "&H00000000"
    back_color = "&H00000000"
    outline_thickness = "14"
    shadow_distance = "14"
    alignment = "10"               # middle-centered
    margin_v = "0"

    ass_content = f"""[Script Info]
Title: Auto Karaoke Subtitles
PlayResX: 1080
PlayResY: 1920
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{subtitle_size},{primary_color},{secondary_color},{outline_color},{back_color},1,0,0,0,100,100,0,0,1,{outline_thickness},{shadow_distance},{alignment},0,0,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def split_long_line(words: list, seg_start: float, seg_end: float, max_chars: int) -> list:
        if not words:
            return [{"words": [], "start": seg_start, "end": seg_end}]
        sub_groups: list = []
        current_group: list = []
        current_length = 0
        current_start = seg_start
        last_end = seg_start
        for word_info in words:
            word = word_info["word"].strip()
            word_length = len(word) + 1
            if current_length + word_length > max_chars and current_group:
                sub_groups.append({
                    "words": current_group[:],
                    "start": current_start,
                    "end": word_info["start"],
                })
                current_group = [word_info]
                current_length = word_length
                current_start = word_info["start"]
            else:
                current_group.append(word_info)
                current_length += word_length
                last_end = word_info["end"]
        if current_group:
            sub_groups.append({"words": current_group, "start": current_start, "end": last_end})
        return sub_groups

    def build_tagged(wlist: list) -> str:
        parts = []
        for w in wlist:
            dur_cs = int((w["end"] - w["start"]) * 100)
            word = w["word"].strip()
            if word and dur_cs > 0:
                parts.append("{\\k" + str(dur_cs) + "}" + word)
        return " ".join(parts)

    for segment in result_segments:
        if progress_cb and total_dur:
            try:
                pct = min(100.0, (segment["end"] / total_dur) * 100)
                progress_cb(round(pct, 1), 100)
            except Exception:
                pass

        start_ms = int(segment["start"] * 1000)
        end_ms = int(segment["end"] * 1000)
        words = segment.get("words", [])

        if not words:
            t0 = ms_to_ass_time(start_ms)
            t1 = ms_to_ass_time(end_ms)
            ass_content += f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{segment['text']}\n"
            continue

        full_tagged = build_tagged(words)
        clean_text = re.sub(r"\{\\k\d+\}", "", full_tagged).strip()

        if len(clean_text) <= max_line_chars:
            t0 = ms_to_ass_time(start_ms)
            t1 = ms_to_ass_time(end_ms)
            ass_content += f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{full_tagged}\n"
        else:
            for group in split_long_line(words, segment["start"], segment["end"], max_line_chars):
                if not group["words"]:
                    continue
                g_start = ms_to_ass_time(int(group["start"] * 1000))
                g_end = ms_to_ass_time(int(group["end"] * 1000))
                group_tagged = build_tagged(group["words"])
                if group_tagged:
                    ass_content += f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{group_tagged}\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)


# ── SRT helpers ───────────────────────────────────────────────────────────────

def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_to_srt(
    input_path: str,
    output_path: str,
    language: str = "fr",
    model_size: str = "medium",
    progress_cb=None,
) -> None:
    """Segment-level SRT transcription via faster_whisper (fallback: openai-whisper on CPU)."""
    import subprocess, json
    total_dur = None
    try:
        dur_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", input_path]
        dur_out = subprocess.check_output(dur_cmd, text=True)
        total_dur = float(json.loads(dur_out)["format"]["duration"])
    except Exception:
        pass
    try:
        from faster_whisper import WhisperModel
        lang = language if language != "auto" else None
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments_gen, _ = model.transcribe(input_path, language=lang)
        segments = []
        for seg in segments_gen:
            segments.append((seg.start, seg.end, seg.text.strip()))
            if progress_cb and total_dur:
                try:
                    pct = min(100.0, (seg.end / total_dur) * 100)
                    progress_cb(round(pct, 1), 100)
                except Exception:
                    pass
    except ImportError:
        import whisper  # type: ignore[import]
        lang = language if language != "auto" else None
        model = whisper.load_model(model_size, device="cpu")
        result = model.transcribe(input_path, language=lang)
        segments = [
            (seg["start"], seg["end"], seg["text"].strip())
            for seg in result["segments"]
        ]

    with open(output_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n")
            f.write(f"{text}\n\n")


# ── TXT helpers ───────────────────────────────────────────────────────────────

def transcribe_to_txt(
    input_path: str,
    output_path: str,
    language: str = "fr",
    model_size: str = "medium",
    progress_cb=None,
) -> None:
    """Plain-text transcription (no timestamps) via faster_whisper."""
    import subprocess, json
    total_dur = None
    try:
        dur_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", input_path]
        dur_out = subprocess.check_output(dur_cmd, text=True)
        total_dur = float(json.loads(dur_out)["format"]["duration"])
    except Exception:
        pass
    try:
        from faster_whisper import WhisperModel
        lang = language if language != "auto" else None
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments_gen, _ = model.transcribe(input_path, language=lang)
        lines = []
        for seg in segments_gen:
            if seg.text.strip():
                lines.append(seg.text.strip())
            if progress_cb and total_dur:
                try:
                    pct = min(100.0, (seg.end / total_dur) * 100)
                    progress_cb(round(pct, 1), 100)
                except Exception:
                    pass
    except ImportError:
        import whisper  # type: ignore[import]
        lang = language if language != "auto" else None
        model = whisper.load_model(model_size, device="cpu")
        result = model.transcribe(input_path, language=lang)
        lines = [seg["text"].strip() for seg in result["segments"] if seg["text"].strip()]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── CLI ───────────────────────────────────────────────────────────────────────

_EXT_TO_FORMAT = {".ass": "ass", ".srt": "srt", ".txt": "txt"}


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("extract-transcript")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option(
        "--format", "-f", "fmt",
        type=click.Choice(["ass", "srt", "txt"]),
        default=None,
        help="Output format (default: inferred from extension, else srt)",
    )
    @click.option("--language", "-l", default="fr", show_default=True, help="Language code or 'auto'")
    @click.option("--model", "-m", default="medium", show_default=True, help="Whisper model size")
    @click.option("--font-size", default=96, show_default=True, help="Font size (ASS only)")
    def extract_transcript_cmd(
        input_file: str,
        output: str | None,
        fmt: str | None,
        language: str,
        model: str,
        font_size: int,
    ):
        """Transcribe a video to ASS karaoke, SRT, or plain TXT subtitles.

        Format is inferred from the output file extension (.ass / .srt / .txt).
        Use --format to override. Defaults to srt when not specified.
        """
        input_path = Path(input_file).resolve()

        # Determine format: explicit flag > output extension > default srt
        if fmt is None and output is not None:
            fmt = _EXT_TO_FORMAT.get(Path(output).suffix.lower())
        if fmt is None:
            fmt = "srt"

        if output:
            output_path = Path(output).resolve()
        else:
            output_path = input_path.parent / f"{input_path.stem}.{fmt}"

        click.echo(f"Transcribing {input_path.name} ({model}, {language}, {fmt})...", err=True)

        if fmt == "ass":
            generate_karaoke_ass(str(input_path), str(output_path), language, model, font_size, progress_cb=None)
        elif fmt == "srt":
            transcribe_to_srt(str(input_path), str(output_path), language, model, progress_cb=None)
        else:
            transcribe_to_txt(str(input_path), str(output_path), language, model, progress_cb=None)

        click.echo(str(output_path))

    return CommandManifest(name="extract-transcript", click_command=extract_transcript_cmd)
