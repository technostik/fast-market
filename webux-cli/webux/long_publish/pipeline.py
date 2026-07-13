from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .models import Job, DEFAULT_VIDEO_SOURCE_PATH
from .utils import (
    _load_publish_cfg,
    _save_meta,
    _yt,
    _pr,
    _video,
    _sound,
    _image,
    _stem,
    _ass_to_plain_text,
    _sanitize_filename,
    _run,
    _run_capture,
    _extract_video_id,
)
from .state import set_active_job, clear_active_job, set_active_proc, clear_active_proc


async def _run_job_safely(coro, job: Job) -> None:
    """Await a pipeline coroutine, turning any unhandled exception into a
    persisted job/step error instead of letting it vanish silently."""
    try:
        await coro
    except Exception as exc:
        import traceback
        traceback.print_exc()
        err_text = f"[error] {type(exc).__name__}: {exc}"
        running_step = next((s for s in job.steps if s.status == "running"), None)
        if running_step:
            running_step.status = "error"
            running_step.end_time = time.time()
            running_step.output = f"{running_step.output}\n{err_text}" if running_step.output else err_text
        job.status = "error"
        job.end_time = time.time()
        _save_meta(job)


def _stop_requested(job: Job) -> bool:
    return getattr(job, "stop_requested", False)


def _finish_step(job: Job, step, rc: int) -> bool:
    """Finalize a step after its subprocess returns. Honors a stop request
    (marks the step skipped + 'stopped') before falling back to error on a
    non-zero exit. Returns True when the pipeline must abort."""
    if _stop_requested(job):
        step.status = "skipped"
        step.end_time = time.time()
        step.output = f"{step.output}\n⏹ Stopped by user" if step.output else "⏹ Stopped by user"
        job.status = "stopped"
        job.end_time = time.time()
        _save_meta(job)
        return True
    if rc != 0:
        step.end_time = time.time()
        step.status = "error"
        job.status = "error"
        _save_meta(job)
        return True
    return False


def _abort_if_stopped(job: Job, step) -> bool:
    if _stop_requested(job):
        step.status = "skipped"
        step.end_time = time.time()
        step.output = (step.output + "\n⏹ Stopped by user") if step.output else "⏹ Stopped by user"
        job.status = "stopped"
        job.end_time = time.time()
        _save_meta(job)
        return True
    return False


async def _run_tracked(job: Job, step, *cmd: str):
    rc, _ = await _run(step, *cmd)
    return _finish_step(job, step, rc)


async def _run_pipeline_from(job: Job, from_step: int) -> None:
    set_active_job(job)
    try:
        await _run_pipeline_core(job, from_step)
    finally:
        clear_active_job()


async def _generate_image_prompt(job: Job, transcript_path: str, pub_cfg: dict) -> str:
    """Build the text prompt for thumbnail image generation. Uses the
    configured thumbnail prompt applied to the transcript; falls back to the
    same image-prompt template storyboard uses; finally falls back to the
    video title."""
    name = pub_cfg.get("default_thumbnail_prompt", "").strip()
    if name and transcript_path and Path(transcript_path).exists():
        rc, out = await _run(None, _pr(), "apply", name, f"transcript=@{transcript_path}")
        if rc == 0 and out.strip():
            return out.strip()
    if transcript_path and Path(transcript_path).exists():
        sb_prompt = await _generate_from_storyboard_prompt(transcript_path)
        if sb_prompt.strip():
            return sb_prompt.strip()
    return job.title or "video thumbnail"


async def _generate_from_storyboard_prompt(transcript_path: str) -> str:
    """Fallback: reuse storyboard's scene_image_prompt template to craft the
    image prompt from the transcript."""
    try:
        from webux.storyboard.config import load_storyboard_config
    except Exception:
        return ""
    try:
        sb = load_storyboard_config()
        template = sb.get("prompts", {}).get("scene_image_prompt", "")
        if not template:
            return ""
        subs = {
            "lang": sb.get("language", "en"),
            "chapter_range": sb.get("chapter_range", "2–5"),
            "scene_range": sb.get("scene_range", "2–5"),
            "scene_duration": sb.get("scene_duration", "15–45 seconds"),
            "narrative_style": sb.get("narrative_style", "documentary narration"),
            "image_style": sb.get("image_style", "cinematic, dramatic lighting"),
        }
        for k, v in subs.items():
            template = template.replace(f"{{{k}}}", str(v))
        # Escape remaining braces (prompt CLI uses {var}) then expose {content}.
        prompt_text = template.replace("{", "{{").replace("}", "}}") + "{content}"
        rc, out = await _run(None, _pr(), "apply", prompt_text, f"content=@{transcript_path}")
        if rc == 0 and out.strip():
            return out.strip()
    except Exception:
        return ""
    return ""


async def _generate_overlay_title(job: Job, transcript_path: str, pub_cfg: dict) -> str:
    """Build the overlay text for the thumbnail. Uses the configured overlay
    prompt applied to the transcript; empty when none configured."""
    name = pub_cfg.get("default_thumbnail_overlay_prompt", "").strip()
    if name and transcript_path and Path(transcript_path).exists():
        rc, out = await _run(None, _pr(), "apply", name, f"transcript=@{transcript_path}")
        if rc == 0 and out.strip():
            return out.strip()
    return ""


async def _run_pipeline_core(job: Job, from_step: int) -> None:
    stem = _stem(job.source)
    pub_cfg = _load_publish_cfg()
    d = Path(pub_cfg.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser().resolve()

    for i in range(from_step):
        if job.steps[i].status == "pending":
            job.steps[i].status = "skipped"

    current_video = job.source

    # ── Step 0: Remove silence + normalize (modal-aware) ──────────────────────
    if from_step <= 0:
        s0 = job.steps[0]
        s0.start_time = time.time()
        s0.status = "running"
        s0.progress = 0.0

        if job.do_remove_silence:
            out_path = str(d / f"{stem}_nosilence.mp4")
            cmd = [_video(), "remove-silence", job.source, "-o", out_path]
            if job.use_modal:
                cmd.append("--modal")
            if await _run_tracked(job, s0, *cmd):
                return
            current_video = out_path
            job.files["no_silence"] = out_path

        if job.do_normalize_volume and Path(current_video).exists():
            audio_out = str(d / f"{stem}_volume_normalized.mp4")
            norm_cmd = [_sound(), "normalize-volume", "apply", current_video, "--output", audio_out]
            if job.use_modal:
                norm_cmd.append("--modal")
            if await _run_tracked(job, s0, *norm_cmd):
                return
            current_video = audio_out
            job.files["audio"] = audio_out
            s0.output += "\n🔊 Normalized"

        s0.end_time = time.time(); s0.status = "done"; s0.progress = 100
        _save_meta(job)
    else:
        av = job.files.get("audio", "")
        if av and Path(av).exists():
            current_video = av
        else:
            nv = job.files.get("no_silence", "")
            if nv and Path(nv).exists():
                current_video = nv

    ass_path = str(d / f"{stem}.ass")
    txt_path = str(d / f"{stem}_transcript.txt")
    skip_transcript = job.transcript_mode == "none"

    # ── Step 1: Extract transcript (modal-aware) ──────────────────────────────
    if from_step <= 1 and not skip_transcript:
        s1 = job.steps[1]
        s1.start_time = time.time()
        s1.status = "running"
        s1.progress = 0.0

        cmd = [
            _video(), "extract-transcript", current_video,
            "-o", ass_path, "-l", job.language, "-m", job.model, "--format", "ass",
        ]
        if job.use_modal:
            cmd.append("--modal")
        if job.transcript_mode == "groq":
            cmd.append("--use-groq")
        if await _run_tracked(job, s1, *cmd):
            return
        s1.end_time = time.time()
        elapsed_s = round(s1.end_time - s1.start_time, 1)
        mode_label = "modal" if job.use_modal else "local"
        plain = _ass_to_plain_text(ass_path)
        s1.output = f"Done in {elapsed_s}s [{mode_label} mode]\n\nTranscript:\n{plain}"
        s1.status = "done"; s1.progress = 100
        with open(txt_path, "w", encoding="utf-8") as _f:
            _f.write(plain)
        job.files["transcript"] = ass_path
        job.files["transcript_txt"] = txt_path
        job.transcript_text = plain
        _save_meta(job)
    else:
        if skip_transcript and from_step <= 1:
            s1 = job.steps[1]
            s1.status = "skipped"
            s1.output = "Skipped (no transcript selected)"
            _save_meta(job)
        ass_path = job.files.get("transcript") or ass_path
        txt_path = job.files.get("transcript_txt") or txt_path
        if not Path(txt_path).exists() and Path(ass_path).exists():
            plain = _ass_to_plain_text(ass_path)
            with open(txt_path, "w", encoding="utf-8") as _f:
                _f.write(plain)

    # ── Step 2: Generate title & description ───────────────────────────────────
    if from_step <= 2:
        s2 = job.steps[2]
        s2.start_time = time.time()
        s2.status = "running"

        if await _run_tracked(job, s2, _pr(), "apply", job.prompt_title, f"transcript=@{txt_path}"):
            return
        title_out = (s2.output or "").strip()

        proc = await asyncio.create_subprocess_exec(
            _pr(), "apply", job.prompt_summary, f"transcript=@{txt_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        set_active_proc(proc)
        try:
            async def _stream(stream, prefix):
                buf = b""
                while True:
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        text = raw.decode(errors="replace").rstrip()
                        if text:
                            if s2.output:
                                s2.output += "\n"
                            s2.output += f"{prefix}{text}"
                if buf:
                    text = buf.decode(errors="replace").rstrip()
                    if text:
                        if s2.output:
                            s2.output += "\n"
                        s2.output += f"{prefix}{text}"

            await asyncio.gather(
                _stream(proc.stdout, ""),
                _stream(proc.stderr, "[err] "),
                proc.wait(),
            )
        finally:
            clear_active_proc()
        if _abort_if_stopped(job, s2):
            return
        if proc.returncode:
            s2.end_time = time.time(); s2.status = "error"; job.status = "error"; _save_meta(job); return

        raw_description = (s2.output or "").strip()
        signature = pub_cfg.get("signature", "").strip()
        parts = []
        if job.description_prefix.strip():
            parts.append(job.description_prefix.strip())
        if job.source_urls:
            sources_block = "Sources:\n" + "\n".join(f"- {u}" for u in job.source_urls)
            parts.append(sources_block)
        parts.append(raw_description)
        if signature:
            parts.append(signature)
        job.title = title_out.strip()
        job.description = "\n\n".join(parts)

        safe_name = _sanitize_filename(job.title)
        ext = Path(current_video).suffix or ".mp4"
        renamed_path = str(Path(current_video).parent / f"{safe_name}{ext}")
        if Path(current_video).resolve() != Path(renamed_path).resolve():
            if not Path(renamed_path).exists():
                os.rename(current_video, renamed_path)
            current_video = renamed_path
            job.files["final_video"] = current_video

        transcript_text = job.transcript_text
        if not transcript_text and txt_path and Path(txt_path).exists():
            try:
                transcript_text = Path(txt_path).read_text(encoding="utf-8")
            except Exception:
                transcript_text = "(transcript unavailable)"
        elif not transcript_text:
            transcript_text = "(transcript unavailable)"

        s2.output = (
            f"Title: {job.title}\n\n"
            f"Description:\n{job.description}\n\n"
            f"Transcript:\n{transcript_text}"
        )
        s2.end_time = time.time(); s2.status = "done"
        _save_meta(job)
    else:
        job.steps[2].status = "skipped"
        if not job.files.get("final_video"):
            job.files["final_video"] = current_video
        fv = job.files.get("final_video", "")
        if fv and Path(fv).exists():
            current_video = fv

    # ── Step 3: Generate thumbnail image (optional) ────────────────────────────
    if not job.do_generate_thumbnail:
        job.steps[3].status = "skipped"
        job.steps[3].output = "Thumbnail generation disabled"
        _save_meta(job)
    elif from_step <= 3:
        s3 = job.steps[3]
        s3.start_time = time.time()
        s3.status = "running"

        if not job.title:
            s3.end_time = time.time(); s3.status = "error"
            s3.output = "[error] No title available to build thumbnail prompt"
            job.status = "error"; _save_meta(job); return

        image_prompt = await _generate_image_prompt(job, txt_path, pub_cfg)
        job.thumbnail_prompt = image_prompt
        overlay_title = job.thumbnail_overlay_title.strip() or await _generate_overlay_title(job, txt_path, pub_cfg)

        thumb_engine = pub_cfg.get("thumbnail_engine", "").strip()
        cmd = [_image(), "generate", image_prompt, "--size", "youtube", "-F", "json", "--output-dir", str(d)]
        if thumb_engine:
            cmd += ["--engine", thumb_engine]
        if overlay_title:
            cmd += ["--title", overlay_title]
        overlay_fg = pub_cfg.get("thumbnail_overlay_fg", "").strip()
        overlay_bg = pub_cfg.get("thumbnail_overlay_bg", "").strip()
        if overlay_fg:
            cmd += ["--overlay-fg", overlay_fg]
        if overlay_bg:
            cmd += ["--overlay-bg", overlay_bg]

        rc, full_stdout = await _run_capture(s3, *cmd)
        if _finish_step(job, s3, rc):
            return

        thumb_path = ""
        thumb_base = ""
        try:
            # The JSON line may be wrapped in other stdout lines; extract it.
            start = full_stdout.find("{")
            end = full_stdout.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(full_stdout[start:end])
                thumb_path = data.get("path", "")
                thumb_base = data.get("base_path", "")
        except (json.JSONDecodeError, ValueError, TypeError):
            thumb_path = ""
            thumb_base = ""
        if not thumb_path or not Path(thumb_path).exists():
            s3.end_time = time.time(); s3.status = "error"
            s3.output += "\n[error] Thumbnail image path not found in generator output"
            job.status = "error"; _save_meta(job); return

        job.files["thumbnail"] = thumb_path
        job.files["thumbnail_base"] = thumb_base or thumb_path
        s3.output += f"\n🖼 Thumbnail: {Path(thumb_path).name}"
        if thumb_base and Path(thumb_base).exists() and thumb_base != thumb_path:
            s3.output += f"\n🖼 Base (no overlay): {Path(thumb_base).name}"
        s3.end_time = time.time(); s3.status = "done"
        _save_meta(job)
    else:
        job.steps[3].status = "skipped"

    # ── Step 4: Append signature video (modal-aware) ───────────────────────────
    if from_step <= 4:
        s4 = job.steps[4]
        s4.start_time = time.time()

        if job.do_add_signature:
            sig_path = pub_cfg.get("signature_video_path", "").strip()
            if sig_path:
                sig_path_obj = Path(sig_path).expanduser()
                if not sig_path_obj.exists():
                    s4.end_time = time.time(); s4.status = "error"
                    s4.output = f"[error] Signature video not found: {sig_path_obj}"
                    job.status = "error"; _save_meta(job); return
                if job.files.get("signature_appended") != "1":
                    safe_name = _sanitize_filename(job.title)
                    ext = Path(current_video).suffix or ".mp4"
                    concat_out = str(Path(current_video).parent / f"with_signature_{safe_name}{ext}")
                    concat_cmd = [_video(), "concat", current_video, str(sig_path_obj), "-o", concat_out]
                    if job.use_modal:
                        concat_cmd.append("--modal")
                    s4.status = "running"
                    if await _run_tracked(job, s4, *concat_cmd):
                        return
                    current_video = concat_out
                    job.files["final_video"] = current_video
                    job.files["signature_appended"] = "1"
                    s4.output += "\n✅ Signature video appended"
            else:
                s4.status = "skipped"
                s4.output = "No signature video configured"
        else:
            s4.status = "skipped"
            s4.output = "Signature disabled"

        s4.end_time = time.time()
        _save_meta(job)
    else:
        fv = job.files.get("final_video", "")
        if fv and Path(fv).exists():
            current_video = fv

    # ── Step 5: Upload to YouTube ──────────────────────────────────────────────
    if job.skip_upload:
        job.steps[5].status = "skipped"
        _save_meta(job)
    else:
        s5 = job.steps[5]
        s5.start_time = time.time()
        s5.status = "running"
        cmd = [
            _yt(), "upload", current_video,
            "--title", job.title,
            "--description", job.description,
            "--privacy", job.privacy,
        ]
        thumb = job.files.get("thumbnail", "")
        if thumb and Path(thumb).exists():
            cmd += ["--thumbnail", thumb]
        rc, url_out = await _run(s5, *cmd)
        if _finish_step(job, s5, rc):
            return

        s5.end_time = time.time(); s5.status = "done"
        watch_url = url_out.strip()
        video_id = _extract_video_id(watch_url)
        if video_id:
            job.video_url = f"https://www.youtube.com/watch?v={video_id}"
            job.studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
        else:
            job.video_url = watch_url
            job.studio_url = ""
        s5.output = f"Uploaded: {job.video_url}"
        _save_meta(job)

    job.status = "done"
    job.end_time = time.time()
    _save_meta(job)
