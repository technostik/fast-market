from __future__ import annotations

import modal
from modal_client.app import app, base_image


def _run_media_pipeline_impl(
    video_bytes: bytes,
    video_name: str,
    do_remove_silence: bool = True,
    threshold: float = -65.0,
    do_transcribe: bool = True,
    ass_bytes: bytes | None = None,
    do_burn_subtitles: bool = True,
    language: str = "fr",
    model_size: str = "medium",
    subtitle_size: int = 96,
    use_groq: bool = False,
) -> dict:
    """
    Run up to three media processing steps inside one Modal container:
      0. Remove silence (moviepy)
      1. Transcribe to ASS karaoke (faster-whisper)
      2. Burn subtitles (ffmpeg)

    Pass ass_bytes + do_transcribe=False to skip transcription and use an
    existing subtitle file (resume-from-step-2 case).

    Returns:
      video_bytes      - final processed video
      video_name       - filename of the output video
      ass_bytes        - ASS subtitle file bytes (empty if not produced)
      ass_txt          - plain-text transcript (empty if not produced)
      original_duration - seconds before silence removal (None if skipped)
      final_duration   - seconds after silence removal (None if skipped)
    """
    import os
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        stem = Path(video_name).stem

        input_path = os.path.join(tmpdir, video_name)
        with open(input_path, "wb") as f:
            f.write(video_bytes)

        current_path = input_path
        original_duration = None
        final_duration = None

        # ── Step 0: Remove silence ────────────────────────────────────────────
        if do_remove_silence:
            out_path = os.path.join(tmpdir, f"{stem}_nosilence.mp4")
            current_path, original_duration, final_duration = _remove_silence(
                current_path, out_path, threshold
            )

        # ── Step 1: Transcribe → ASS ──────────────────────────────────────────
        ass_path = os.path.join(tmpdir, f"{stem}.ass")
        if do_transcribe:
            if use_groq:
                groq_api_key = os.environ.get("GROQ_API_KEY", "")
                _groq_transcribe_to_ass(current_path, ass_path, language, groq_api_key, subtitle_size)
            else:
                _transcribe_to_ass(current_path, ass_path, language, model_size, subtitle_size)
        elif ass_bytes:
            with open(ass_path, "wb") as f:
                f.write(ass_bytes)

        # ── Step 2: Burn subtitles ────────────────────────────────────────────
        if do_burn_subtitles and os.path.exists(ass_path):
            out_path = os.path.join(tmpdir, f"{stem}_subtitled.mp4")
            _burn_subtitles(current_path, ass_path, out_path, subtitle_size)
            current_path = out_path

        # ── Collect outputs ───────────────────────────────────────────────────
        with open(current_path, "rb") as f:
            out_video_bytes = f.read()

        out_ass_bytes = b""
        if os.path.exists(ass_path):
            with open(ass_path, "rb") as f:
                out_ass_bytes = f.read()

        ass_txt = _ass_to_plain_text(out_ass_bytes.decode("utf-8", errors="replace")) if out_ass_bytes else ""

        return {
            "video_bytes": out_video_bytes,
            "video_name": Path(current_path).name,
            "ass_bytes": out_ass_bytes,
            "ass_txt": ass_txt,
            "original_duration": original_duration,
            "final_duration": final_duration,
        }


@app.function(image=base_image, timeout=1800, secrets=[modal.Secret.from_dotenv()])
def run_media_pipeline(
    video_bytes: bytes,
    video_name: str,
    do_remove_silence: bool = True,
    threshold: float = -65.0,
    do_transcribe: bool = True,
    ass_bytes: bytes | None = None,
    do_burn_subtitles: bool = True,
    language: str = "fr",
    model_size: str = "medium",
    subtitle_size: int = 96,
    use_groq: bool = False,
) -> dict:
    return _run_media_pipeline_impl(
        video_bytes, video_name, do_remove_silence, threshold, do_transcribe,
        ass_bytes, do_burn_subtitles, language, model_size, subtitle_size, use_groq
    )


@app.function(image=base_image, timeout=1800, secrets=[modal.Secret.from_dotenv()])
def remote_remove_silence(video_bytes: bytes, video_name: str, threshold: float = -65.0) -> dict:
    return _run_media_pipeline_impl(
        video_bytes,
        video_name,
        do_remove_silence=True,
        threshold=threshold,
        do_transcribe=False,
        ass_bytes=None,
        do_burn_subtitles=False,
    )


@app.function(image=base_image, timeout=1800, secrets=[modal.Secret.from_dotenv()])
def remote_extract_transcript(
    video_bytes: bytes,
    video_name: str,
    language: str = "fr",
    model_size: str = "medium",
    subtitle_size: int = 96,
    use_groq: bool = False,
    output_format: str = "ass",
) -> dict:
    if output_format == "ass":
        return _run_media_pipeline_impl(
            video_bytes,
            video_name,
            do_remove_silence=False,
            do_transcribe=True,
            ass_bytes=None,
            do_burn_subtitles=False,
            language=language,
            model_size=model_size,
            subtitle_size=subtitle_size,
            use_groq=use_groq,
        )

    import os
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, video_name)
        with open(input_path, "wb") as f:
            f.write(video_bytes)
        output_path = os.path.join(tmpdir, f"{Path(video_name).stem}.{output_format}")
        if output_format == "srt":
            _transcribe_to_srt(input_path, output_path, language, model_size)
        elif output_format == "txt":
            _transcribe_to_txt(input_path, output_path, language, model_size)
        else:
            raise ValueError(f"unsupported output_format: {output_format}")
        with open(output_path, "rb") as f:
            transcript_bytes = f.read()
        text = transcript_bytes.decode("utf-8", errors="replace")
        return {
            "video_bytes": video_bytes,
            "video_name": video_name,
            "ass_bytes": b"",
            "transcript_bytes": transcript_bytes,
            "ass_txt": text,
            "original_duration": None,
            "final_duration": None,
        }


@app.function(image=base_image, timeout=1800, secrets=[modal.Secret.from_dotenv()])
def remote_burn_subtitles(
    video_bytes: bytes,
    video_name: str,
    ass_bytes: bytes,
    subtitle_size: int = 96,
) -> dict:
    return _run_media_pipeline_impl(
        video_bytes,
        video_name,
        do_remove_silence=False,
        do_transcribe=False,
        ass_bytes=ass_bytes,
        do_burn_subtitles=True,
        subtitle_size=subtitle_size,
    )


# ── Helpers (run on the Modal worker) ────────────────────────────────────────

def _remove_silence(
    input_path: str,
    output_path: str,
    threshold: float,
) -> tuple[str, float, float]:
    import numpy as np
    from moviepy import VideoFileClip, concatenate_videoclips

    video = VideoFileClip(input_path)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = _detect_silence_segments(audio_array, video.audio.fps, threshold)
    if not segments:
        video.close()
        raise RuntimeError("No non-silent segments detected — check threshold")

    clips = [video.subclipped(start, end) for start, end in segments]
    final = concatenate_videoclips(clips)

    import os
    temp_audio = os.path.join(os.path.dirname(os.path.abspath(output_path)), "temp-audio.m4a")
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=temp_audio,
        remove_temp=True,
        audio_bitrate="192k",
        preset="medium",
    )
    final_duration = final.duration
    video.close()
    final.close()
    for c in clips:
        c.close()
    return output_path, original_duration, final_duration


def _detect_silence_segments(
    audio_array,
    sample_rate: int,
    threshold_db: float,
) -> list[tuple[float, float]]:
    import numpy as np

    threshold_amp = 10 ** (threshold_db / 20)
    window_size = int(sample_rate / 30)
    if window_size == 0:
        return []
    num_windows = len(audio_array) // window_size
    if num_windows == 0:
        return []
    audio_array = audio_array[: num_windows * window_size]
    rms = np.array([
        np.sqrt(np.mean(w ** 2))
        for w in np.array_split(audio_array, num_windows)
    ])
    is_non_silent = rms >= threshold_amp
    time_per_window = window_size / sample_rate
    segments: list[tuple[float, float]] = []
    start_idx = None
    for i, active in enumerate(is_non_silent):
        if active and start_idx is None:
            start_idx = i
        elif not active and start_idx is not None:
            segments.append((start_idx * time_per_window, i * time_per_window))
            start_idx = None
    if start_idx is not None:
        segments.append((start_idx * time_per_window, len(is_non_silent) * time_per_window))
    return segments


def _transcribe_to_ass(
    input_path: str,
    output_ass_path: str,
    language: str,
    model_size: str,
    subtitle_size: int = 96,
) -> None:
    import re
    from faster_whisper import WhisperModel

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

    primary_color = "&H0000FF00"
    secondary_color = "&H00FFFFFF"
    outline_color = "&H00000000"
    back_color = "&H00000000"

    ass_content = f"""[Script Info]
Title: Auto Karaoke Subtitles
PlayResX: 1080
PlayResY: 1920
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{subtitle_size},{primary_color},{secondary_color},{outline_color},{back_color},1,0,0,0,100,100,0,0,1,14,14,10,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def ms_to_ass_time(ms: int) -> str:
        h = ms // 3600000; ms %= 3600000
        m = ms // 60000; ms %= 60000
        s = ms // 1000; cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}:{cs:02d}"

    def build_tagged(wlist: list) -> str:
        parts = []
        for w in wlist:
            dur_cs = int((w["end"] - w["start"]) * 100)
            word = w["word"].strip()
            if word and dur_cs > 0:
                parts.append("{\\k" + str(dur_cs) + "}" + word)
        return " ".join(parts)

    max_chars = 35

    for segment in result_segments:
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

        if len(clean_text) <= max_chars:
            t0 = ms_to_ass_time(start_ms)
            t1 = ms_to_ass_time(end_ms)
            ass_content += f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{full_tagged}\n"
        else:
            sub_groups: list = []
            current_group: list = []
            current_length = 0
            current_start = segment["start"]
            for word_info in words:
                word = word_info["word"].strip()
                word_length = len(word) + 1
                if current_length + word_length > max_chars and current_group:
                    sub_groups.append({"words": current_group[:], "start": current_start, "end": word_info["start"]})
                    current_group = [word_info]
                    current_length = word_length
                    current_start = word_info["start"]
                else:
                    current_group.append(word_info)
                    current_length += word_length
            if current_group:
                last_end = current_group[-1]["end"]
                sub_groups.append({"words": current_group, "start": current_start, "end": last_end})

            for group in sub_groups:
                if not group["words"]:
                    continue
                g_start = ms_to_ass_time(int(group["start"] * 1000))
                g_end = ms_to_ass_time(int(group["end"] * 1000))
                group_tagged = build_tagged(group["words"])
                if group_tagged:
                    ass_content += f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{group_tagged}\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)


def _groq_transcribe_to_ass(
    input_path: str,
    output_ass_path: str,
    language: str,
    groq_api_key: str,
    subtitle_size: int = 96,
) -> None:
    import os
    import re
    import subprocess
    import tempfile
    import requests

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=os.path.dirname(output_ass_path)) as _tmp:
        tmp_audio = _tmp.name

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", tmp_audio],
            check=True, capture_output=True,
        )
        form_data = [
            ("model", "whisper-large-v3"),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if language and language != "auto":
            form_data.append(("language", language))
        with open(tmp_audio, "rb") as _f:
            resp = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_api_key}"},
                files={"file": (os.path.basename(tmp_audio), _f, "audio/mpeg")},
                data=form_data,
                timeout=120,
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

    result_segments = []
    word_idx = 0
    for seg in raw_segments:
        seg_words = []
        while word_idx < len(flat_words):
            w = flat_words[word_idx]
            if w["start"] < seg["end"] - 0.001:
                seg_words.append({"word": w["word"].strip(), "start": w["start"], "end": w["end"]})
                word_idx += 1
            else:
                break
        result_segments.append({"start": seg["start"], "end": seg["end"], "text": seg["text"].strip(), "words": seg_words})
    if word_idx < len(flat_words):
        remaining = flat_words[word_idx:]
        result_segments.append({
            "start": remaining[0]["start"],
            "end": remaining[-1]["end"],
            "text": " ".join(w["word"].strip() for w in remaining),
            "words": [{"word": w["word"].strip(), "start": w["start"], "end": w["end"]} for w in remaining],
        })

    primary_color = "&H0000FF00"
    secondary_color = "&H00FFFFFF"
    outline_color = "&H00000000"
    back_color = "&H00000000"

    ass_content = f"""[Script Info]
Title: Auto Karaoke Subtitles
PlayResX: 1080
PlayResY: 1920
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{subtitle_size},{primary_color},{secondary_color},{outline_color},{back_color},1,0,0,0,100,100,0,0,1,14,14,10,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _ms(ms: int) -> str:
        h = ms // 3600000; ms %= 3600000
        m = ms // 60000; ms %= 60000
        s = ms // 1000; cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}:{cs:02d}"

    def _tagged(wlist):
        parts = []
        for w in wlist:
            dur_cs = int((w["end"] - w["start"]) * 100)
            word = w["word"].strip()
            if word and dur_cs > 0:
                parts.append("{\\k" + str(dur_cs) + "}" + word)
        return " ".join(parts)

    max_chars = 35
    for seg in result_segments:
        start_ms = int(seg["start"] * 1000)
        end_ms = int(seg["end"] * 1000)
        words = seg.get("words", [])
        if not words:
            ass_content += f"Dialogue: 0,{_ms(start_ms)},{_ms(end_ms)},Default,,0,0,0,,{seg['text']}\n"
            continue
        full_tagged = _tagged(words)
        clean = re.sub(r"\{\\k\d+\}", "", full_tagged).strip()
        if len(clean) <= max_chars:
            ass_content += f"Dialogue: 0,{_ms(start_ms)},{_ms(end_ms)},Default,,0,0,0,,{full_tagged}\n"
        else:
            sub_groups, cur, cur_len, cur_start = [], [], 0, seg["start"]
            for wi in words:
                wlen = len(wi["word"]) + 1
                if cur_len + wlen > max_chars and cur:
                    sub_groups.append({"words": cur[:], "start": cur_start, "end": wi["start"]})
                    cur, cur_len, cur_start = [wi], wlen, wi["start"]
                else:
                    cur.append(wi); cur_len += wlen
            if cur:
                sub_groups.append({"words": cur, "start": cur_start, "end": cur[-1]["end"]})
            for grp in sub_groups:
                if not grp["words"]:
                    continue
                tagged = _tagged(grp["words"])
                if tagged:
                    ass_content += f"Dialogue: 0,{_ms(int(grp['start']*1000))},{_ms(int(grp['end']*1000))},Default,,0,0,0,,{tagged}\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)


def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _transcribe_to_srt(input_path: str, output_path: str, language: str, model_size: str) -> None:
    from faster_whisper import WhisperModel

    lang = language if language != "auto" else None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_gen, _ = model.transcribe(input_path, language=lang)
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments_gen, 1):
            f.write(f"{i}\n")
            f.write(f"{_fmt_srt_time(seg.start)} --> {_fmt_srt_time(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")


def _transcribe_to_txt(input_path: str, output_path: str, language: str, model_size: str) -> None:
    from faster_whisper import WhisperModel

    lang = language if language != "auto" else None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_gen, _ = model.transcribe(input_path, language=lang)
    lines = [seg.text.strip() for seg in segments_gen if seg.text.strip()]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    subtitle_size: int = 96,
) -> None:
    import os
    import subprocess

    abs_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"Alignment=10,Fontsize={subtitle_size},"
        "MarginL=0,MarginR=0,MarginV=0,"
        "Outline=8,Shadow=14,BackColour=&H80000000&"
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles='{abs_ass}':force_style='{force_style}'",
        "-vcodec", "h264",
        "-acodec", "aac",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _ass_to_plain_text(ass_content: str) -> str:
    import re
    lines = []
    for line in ass_content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = parts[9].strip()
        text = re.sub(r"\{[^}]*\}", "", text)
        if text:
            lines.append(text)
    return "\n".join(lines)
