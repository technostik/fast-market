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
    _stem,
    _ass_to_plain_text,
    _get_video_duration,
    _sanitize_filename,
    _effective_limit_seconds,
    _run,
    _extract_video_id,
)
from .state import set_active_job, clear_active_job, set_active_proc, clear_active_proc


async def _run_job_safely(coro, job: Job) -> None:
    """Await a pipeline coroutine, turning any unhandled exception into a
    persisted job/step error instead of letting it vanish silently (e.g. when
    scheduled via asyncio.create_task with nothing awaiting the result)."""
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
    """If a stop was requested, finalize the step + job as stopped and return
    True so the caller can abort the pipeline. Use after a tracked subprocess
    whose own exit code does not decide success/failure (e.g. analysis steps)."""
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
    """Run a subprocess as a tracked, interruptible pipeline step.

    Streams stdout/stderr into the step output, registers the process so a
    stop request can terminate it, then finalizes the step. Returns True when
    the pipeline must abort (error or stop)."""
    rc, _ = await _run(step, *cmd)
    return _finish_step(job, step, rc)


async def _run_pipeline_from(job: Job, from_step: int) -> None:
    set_active_job(job)
    try:
        await _run_pipeline_core(job, from_step)
    finally:
        clear_active_job()


async def _run_pipeline_core(job: Job, from_step: int) -> None:
    stem = _stem(job.source)
    pub_cfg = _load_publish_cfg()
    d = Path(pub_cfg.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser().resolve()

    for i in range(from_step):
        if job.steps[i].status == "pending":
            job.steps[i].status = "skipped"

    current_video = job.source

    # ── Video CLI path for steps 0-2 ──────────────────────────────────────────
    if from_step <= 0:
        s0 = job.steps[0]
        s0.start_time = time.time()
        s0.status = "running"
        s0.progress = 0.0

        # ── Remove silence (optional, modal-aware) ──
        if job.do_remove_silence:
            out_path = str(d / f"{stem}_nosilence.mp4")
            cmd = [_video(), "remove-silence", job.source, "-o", out_path]
            if job.use_modal:
                cmd.append("--modal")
            if await _run_tracked(job, s0, *cmd):
                return
            duration = await _get_video_duration(out_path)
            # Subtract the signature video length: it is appended later (step 3)
            # and would otherwise push the final upload past YouTube's 3-min limit.
            sig_duration = 0.0
            if job.do_add_signature:
                sig_path = pub_cfg.get("signature_video_path", "").strip()
                if sig_path:
                    sig_path_obj = Path(sig_path).expanduser()
                    if sig_path_obj.exists():
                        sig_duration = await _get_video_duration(str(sig_path_obj))
            effective_limit = _effective_limit_seconds(sig_duration)
            if duration > effective_limit:
                s0.end_time = time.time(); s0.status = "error"
                s0.output += f"\nvideo too long (incl. signature): {duration:.0f}s > {effective_limit:.0f}s"
                job.status = "error"; _save_meta(job); return
            s0.output += f"\n⏱ Duration: {duration:.0f}s (limit {effective_limit:.0f}s incl. signature)"
            current_video = out_path
            job.files["no_silence"] = out_path

        # ── Volume normalization (optional, modal-aware) ──
        if job.do_normalize_volume:
            audio_out = str(d / f"{stem}_volume_normalized.mp4")
            norm_cmd = [_sound(), "normalize-volume", "apply", current_video, "--output", audio_out]
            if job.use_modal:
                norm_cmd.append("--modal")
            norm_proc = await asyncio.create_subprocess_exec(
                *norm_cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            set_active_proc(norm_proc)
            try:
                await norm_proc.communicate()
            finally:
                clear_active_proc()
            if _abort_if_stopped(job, s0):
                return
            if norm_proc.returncode == 0:
                current_video = audio_out
                job.files["audio"] = audio_out
                s0.output += "\n🔊 Normalized"

        # ── Audio analysis (modal-aware) ──
        if Path(current_video).exists():

            if job.do_charisma:
                charisma_cmd = [_sound(), "charisma", current_video, "--format", "json"]
                if job.use_modal:
                    charisma_cmd.append("--modal")
                charisma_proc = await asyncio.create_subprocess_exec(
                    *charisma_cmd,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                set_active_proc(charisma_proc)
                try:
                    charisma_stdout, _ = await charisma_proc.communicate()
                finally:
                    clear_active_proc()
                if _abort_if_stopped(job, s0):
                    return
                if charisma_proc.returncode == 0:
                    try:
                        char_data = json.loads(charisma_stdout)
                        score = char_data.get("charisma_score", "?")
                        notes = char_data.get("notes", "")
                        tip = notes.replace('"', '&quot;')
                        job.files["charisma_score"] = str(score)
                        job.files["charisma_notes"] = notes
                        s0.output += f'🎙 Charisma: <span title="{tip}" style="cursor:help;border-bottom:1px dotted var(--dim);">{score}</span>'
                    except (json.JSONDecodeError, ValueError, TypeError):
                        s0.output += "🎙 Charisma: failed"
                else:
                    s0.output += "🎙 Charisma: failed"

            measure_cmd = [_sound(), "normalize-volume", "measure", current_video, "--format", "json"]
            if job.use_modal:
                measure_cmd.append("--modal")
            measure_proc = await asyncio.create_subprocess_exec(
                *measure_cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            set_active_proc(measure_proc)
            try:
                measure_stdout, _ = await measure_proc.communicate()
            finally:
                clear_active_proc()
            if _abort_if_stopped(job, s0):
                return
            if measure_proc.returncode == 0:
                try:
                    vol_data = json.loads(measure_stdout)
                    mean_vol = vol_data.get("mean_volume_db", "?")
                    s0.output += f"\n🔊 Volume: {mean_vol} dB"
                except (json.JSONDecodeError, ValueError, TypeError):
                    s0.output += "\n🔊 Volume: failed"
            else:
                s0.output += "\n🔊 Volume: failed"

        s0.end_time = time.time(); s0.status = "done"; s0.progress = 100
        _save_meta(job)
    else:
        nv = job.files.get("no_silence", "")
        if nv and Path(nv).exists():
            current_video = nv

    ass_path = str(d / f"{stem}.ass")
    txt_path = str(d / f"{stem}_transcript.txt")

    skip_transcript = job.transcript_mode == "none"

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

    if from_step <= 2:
        s2 = job.steps[2]
        if job.do_burn_subtitles and not skip_transcript:
            s2.start_time = time.time()
            s2.status = "running"
            out_path = str(d / f"{stem}_subtitled.mp4")
            cmd = [_video(), "burn-subtitles", current_video, ass_path, "-o", out_path]
            if job.use_modal:
                cmd.append("--modal")
            if await _run_tracked(job, s2, *cmd):
                return
            s2.end_time = time.time(); s2.status = "done"; s2.progress = 100
            current_video = out_path
            job.files["subtitled"] = out_path
        else:
            if skip_transcript:
                s2.output = "Skipped (no transcript selected)"
            s2.status = "skipped"
        _save_meta(job)
    else:
        # Prefer the already-renamed final video (set by step 3), then subtitled, then no_silence
        for _key in ("final_video", "subtitled", "no_silence"):
            _v = job.files.get(_key, "")
            if _v and Path(_v).exists():
                current_video = _v
                break

    if not (job.files.get("final_video") and Path(job.files["final_video"]).exists()):
        job.files["final_video"] = current_video
    await _run_llm_and_upload(job, txt_path, current_video, from_step)


async def _run_llm_and_upload(job: Job, transcript_path: str, final_video: str, from_step: int = 3) -> None:
    pub_cfg = _load_publish_cfg()

    if from_step <= 3:
        s3 = job.steps[3]
        s3.start_time = time.time()
        s3.status = "running"

        if await _run_tracked(job, s3, _pr(), "apply", job.prompt_title, f"transcript=@{transcript_path}"):
            return
        title_out = (s3.output or "").strip()

        proc = await asyncio.create_subprocess_exec(
            _pr(), "apply", job.prompt_summary, f"transcript=@{transcript_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        set_active_proc(proc)
        try:
            async def _stream(stream, prefix):
                while True:
                    line = await stream.readline()
                    if not line: break
                    text = line.decode(errors="replace").rstrip()
                    if text:
                        if s3.output: s3.output += "\n"
                        s3.output += f"{prefix}{text}"

            await asyncio.gather(
                _stream(proc.stdout, ""),
                _stream(proc.stderr, "[err] "),
                proc.wait(),
            )
        finally:
            clear_active_proc()
        if _abort_if_stopped(job, s3):
            return
        if proc.returncode:
            s3.end_time = time.time(); s3.status = "error"; job.status = "error"; _save_meta(job); return

        raw_description = (s3.output or "").strip()
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

        # Optional content check — non-blocking, just a warning
        if job.prompt_check:
            try:
                chk_proc = await asyncio.create_subprocess_exec(
                    _pr(), "apply", job.prompt_check, f"transcript=@{transcript_path}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                set_active_proc(chk_proc)
                try:
                    chk_stdout, _ = await chk_proc.communicate()
                finally:
                    clear_active_proc()
                if _abort_if_stopped(job, s3):
                    return
                if chk_proc.returncode == 0:
                    job.check_result = chk_stdout.decode(errors="replace").strip()
            except Exception:
                pass

        safe_name = _sanitize_filename(job.title)
        ext = Path(final_video).suffix or ".mp4"
        renamed_path = str(Path(final_video).parent / f"{safe_name}{ext}")
        if Path(final_video).resolve() != Path(renamed_path).resolve():
            if not Path(renamed_path).exists():
                os.rename(final_video, renamed_path)
            final_video = renamed_path
            job.files["final_video"] = final_video

        # ── Append signature video (optional, modal-aware) ──
        if job.do_add_signature:
            sig_path = pub_cfg.get("signature_video_path", "").strip()
            if sig_path:
                sig_path_obj = Path(sig_path).expanduser()
                if not sig_path_obj.exists():
                    # FAIL LOUDLY: a signature path is configured but missing
                    s3.end_time = time.time(); s3.status = "error"
                    s3.output += f"\n[error] Signature video not found: {sig_path_obj}"
                    job.status = "error"; _save_meta(job); return
                if job.files.get("signature_appended") != "1":
                    concat_out = str(Path(final_video).parent / f"with_signature_{safe_name}{ext}")
                    concat_cmd = [_video(), "concat", final_video, str(sig_path_obj), "-o", concat_out]
                    if job.use_modal:
                        concat_cmd.append("--modal")
                    if await _run_tracked(job, s3, *concat_cmd):
                        return
                    final_video = concat_out
                    job.files["final_video"] = final_video
                    job.files["signature_appended"] = "1"
                    s3.output += "\n✅ Signature video appended"
            # else: do_add_signature=True but no path configured → nothing to append, silent no-op

        transcript_text = job.transcript_text
        if not transcript_text and transcript_path and Path(transcript_path).exists():
            try:
                transcript_text = Path(transcript_path).read_text(encoding="utf-8")
            except Exception:
                transcript_text = "(transcript unavailable)"
        elif not transcript_text:
            transcript_text = "(transcript unavailable)"

        check_line = ""
        if job.check_result is not None:
            if job.check_result.strip().rstrip(".!").strip().upper() == "OK":
                check_line = "\n\n✅ Check: OK"
            else:
                check_line = f"\n\n⚠ Check: {job.check_result}"

        s3.output = (
            f"Title: {job.title}\n\n"
            f"Description:\n{job.description}\n\n"
            f"Transcript:\n{transcript_text}"
            + check_line
        )
        s3.end_time = time.time(); s3.status = "done"
        _save_meta(job)
    else:
        job.steps[3].status = "skipped"

    if from_step > 4:
        # Upload already done — skip it, preserve existing status from meta
        if job.steps[4].status == "pending":
            job.steps[4].status = "skipped"
    elif job.skip_upload:
        job.steps[4].status = "skipped"
        _save_meta(job)
    else:
        s4 = job.steps[4]
        s4.start_time = time.time()
        s4.status = "running"
        rc, url_out = await _run(
            s4, _yt(), "upload", final_video,
            "--title", job.title,
            "--description", job.description,
            "--privacy", job.privacy,
        )
        if _finish_step(job, s4, rc):
            return

        s4.end_time = time.time(); s4.status = "done"
        watch_url = url_out.strip()
        video_id = _extract_video_id(watch_url)
        if video_id:
            job.video_url = f"https://www.youtube.com/shorts/{video_id}"
            job.studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
        else:
            job.video_url = watch_url
            job.studio_url = ""
        _save_meta(job)

    if not job.do_ignore_post_publish:
        await _run_post_publish_step(job, final_video)
    else:
        job.steps[5].status = "skipped"
        job.steps[6].status = "skipped"
        job.status = "done"
        job.end_time = time.time()
        _save_meta(job)


async def _run_post_publish_step(job: Job, final_video: str) -> None:
    """Run step 5 (post-publish script). Sets job.status='error' on failure."""
    if job.do_ignore_post_publish:
        job.steps[5].status = "skipped"
        job.status = "done"
        job.end_time = time.time()
        _save_meta(job)
        return
    pub_cfg = _load_publish_cfg()
    s5 = job.steps[5]
    s5.start_time = time.time()
    s5.status = "running"
    s5.output = ""

    post_script = pub_cfg.get("post_publish_script", "").strip()
    if post_script:
        script_path = Path(post_script)
        print(f"[post-publish] Running: bash {script_path}", flush=True)
        if script_path.is_file():
            try:
                final_for_script = job.files.get("final_video", final_video)
                proc = await asyncio.create_subprocess_exec(
                    "bash", str(script_path), final_for_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy(),
                )
                set_active_proc(proc)

                async def _stream(stream, prefix):
                    while True:
                        line = await stream.readline()
                        if not line: break
                        text = line.decode(errors="replace").rstrip()
                        if text:
                            print(f"[post-publish]{prefix} {text}", flush=True)
                            if s5.output: s5.output += "\n"
                            s5.output += f"{prefix}{text}"

                await asyncio.gather(
                    _stream(proc.stdout, ""),
                    _stream(proc.stderr, "[err]"),
                    proc.wait(),
                )
                clear_active_proc()
                if _abort_if_stopped(job, s5):
                    return
                rc = proc.returncode
                s5.status = "done" if rc == 0 else "error"
                if rc != 0:
                    print(f"[post-publish] Script exited with code {rc}", flush=True)
                    job.status = "error"
                else:
                    print("[post-publish] Done.", flush=True)
            except Exception as exc:
                print(f"[post-publish] Exception: {exc}", flush=True)
                s5.output = str(exc)
                s5.status = "error"
                job.status = "error"
        else:
            msg = f"Script not found: {post_script}"
            print(f"[post-publish] {msg}", flush=True)
            s5.output = msg
            s5.status = "error"
            job.status = "error"
    else:
        print("[post-publish] No script configured — skipped.", flush=True)
        s5.status = "skipped"

    s5.end_time = time.time()
    if job.steps[6].status == "pending":
        # Run transcript script is manual-only — never auto-started by the pipeline.
        job.steps[6].status = "skipped"
    if job.status != "error":
        job.status = "done"
        job.end_time = time.time()
    _save_meta(job)


async def _run_transcript_script(job: Job, transcript_path: str) -> None:
    """Run step 6 (transcript script). Only triggered manually — never auto-started."""
    if job.do_ignore_post_publish:
        job.steps[6].status = "skipped"
        job.status = "done"
        job.end_time = time.time()
        _save_meta(job)
        return
    pub_cfg = _load_publish_cfg()
    s6 = job.steps[6]
    s6.start_time = time.time()
    s6.status = "running"
    s6.output = ""

    script = pub_cfg.get("transcript_script", "").strip()
    if script:
        script_path = Path(script)
        print(f"[transcript-script] Running: bash {script_path}", flush=True)
        if script_path.is_file():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", str(script_path), transcript_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=os.environ.copy(),
                )
                set_active_proc(proc)

                async def _stream(stream, prefix):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode(errors="replace").rstrip()
                        if text:
                            print(f"[transcript-script]{prefix} {text}", flush=True)
                            if s6.output:
                                s6.output += "\n"
                            s6.output += f"{prefix}{text}"

                await asyncio.gather(
                    _stream(proc.stdout, ""),
                    _stream(proc.stderr, "[err]"),
                    proc.wait(),
                )
                clear_active_proc()
                if _abort_if_stopped(job, s6):
                    return
                rc = proc.returncode
                s6.status = "done" if rc == 0 else "error"
                if rc != 0:
                    print(f"[transcript-script] Script exited with code {rc}", flush=True)
                    job.status = "error"
                else:
                    print("[transcript-script] Done.", flush=True)
            except Exception as exc:
                print(f"[transcript-script] Exception: {exc}", flush=True)
                s6.output = str(exc)
                s6.status = "error"
                job.status = "error"
        else:
            msg = f"Script not found: {script}"
            print(f"[transcript-script] {msg}", flush=True)
            s6.output = msg
            s6.status = "error"
            job.status = "error"
    else:
        print("[transcript-script] No script configured — skipped.", flush=True)
        s6.status = "skipped"

    s6.end_time = time.time()
    if job.status != "error":
        job.status = "done"
        job.end_time = time.time()
    _save_meta(job)
