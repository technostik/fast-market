from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from .models import Job, DEFAULT_VIDEO_SOURCE_PATH
from .utils import (
    _load_publish_cfg,
    _save_meta,
    _yt,
    _pr,
    _stem,
    _ass_to_plain_text,
    _get_video_duration,
    _sanitize_filename,
    _run,
    _extract_video_id,
)

try:
    from commands.remove_silence.register import remove_silence_simple
except Exception:
    remove_silence_simple = None

try:
    from commands.burn_subtitles.register import burn_ass_subtitles
except Exception:
    burn_ass_subtitles = None

try:
    from commands.extract_transcript.register import (
        generate_karaoke_ass,
        transcribe_to_srt,
        transcribe_to_txt,
    )
except Exception:
    generate_karaoke_ass = transcribe_to_srt = transcribe_to_txt = None


async def _run_modal_steps(
    job: Job,
    from_step: int,
    current_video: str,
    d: Path,
    stem: str,
) -> tuple[str, str, str]:
    """Run steps 0-2 remotely on Modal. Returns (current_video, ass_path, txt_path)."""
    from modal_client.app import app
    from modal_client.remote_steps import run_media_pipeline

    do_remove_silence = job.do_remove_silence and from_step <= 0
    do_transcribe = from_step <= 1
    do_burn_subtitles = job.do_burn_subtitles

    # Pre-existing ASS for resume-from-step-2
    ass_bytes: bytes | None = None
    if from_step == 2:
        existing_ass = job.files.get("transcript", "")
        if existing_ass and Path(existing_ass).exists():
            ass_bytes = Path(existing_ass).read_bytes()
        do_transcribe = False

    # Mark steps as running
    for i in range(from_step, 3):
        s = job.steps[i]
        s.start_time = time.time()
        s.status = "running"
        s.progress = 0.0

    video_bytes = Path(current_video).read_bytes()
    video_name = Path(current_video).name

    try:
        async with app.run():
            if app.app_id:
                job.modal_url = f"https://modal.com/id/{app.app_id}"
            result = await asyncio.to_thread(
                run_media_pipeline.remote,
                video_bytes,
                video_name,
                do_remove_silence,
                -65.0,
                do_transcribe,
                ass_bytes,
                do_burn_subtitles,
                job.language,
                job.model,
                96,
            )
    except Exception as exc:
        for i in range(from_step, 3):
            job.steps[i].status = "error"
            job.steps[i].output = str(exc)
            job.steps[i].end_time = time.time()
        job.status = "error"
        _save_meta(job)
        return current_video, "", ""

    now = time.time()

    # ── Write outputs to disk ──────────────────────────────────────────────
    out_video_name = result["video_name"]
    out_video_path = str(d / out_video_name)
    Path(out_video_path).write_bytes(result["video_bytes"])

    ass_path = str(d / f"{stem}.ass")
    if result["ass_bytes"]:
        Path(ass_path).write_bytes(result["ass_bytes"])

    txt_path = str(d / f"{stem}_transcript.txt")
    if result["ass_txt"]:
        Path(txt_path).write_text(result["ass_txt"], encoding="utf-8")

    # ── Update step statuses ───────────────────────────────────────────────
    if from_step <= 0:
        s0 = job.steps[0]
        s0.end_time = now
        if do_remove_silence:
            orig = result["original_duration"]
            final = result["final_duration"]
            s0.status = "done"
            s0.progress = 100
            s0.output = f"⏱ Duration: {final:.0f}s" if final else ""
            job.files["no_silence"] = out_video_path
        else:
            s0.status = "skipped"

    if from_step <= 1:
        s1 = job.steps[1]
        s1.end_time = now
        elapsed = round(now - s1.start_time, 1)
        s1.status = "done"
        s1.progress = 100
        s1.output = f"Done in {elapsed}s [modal]"
        job.files["transcript"] = ass_path
        job.files["transcript_txt"] = txt_path

    if from_step <= 2:
        s2 = job.steps[2]
        s2.end_time = now
        if do_burn_subtitles:
            s2.status = "done"
            s2.progress = 100
            job.files["subtitled"] = out_video_path
        else:
            s2.status = "skipped"

    _save_meta(job)
    return out_video_path, ass_path, txt_path


async def _run_pipeline_from(job: Job, from_step: int) -> None:
    stem = _stem(job.source)
    pub_cfg = _load_publish_cfg()
    d = Path(pub_cfg.get("video_source_path", DEFAULT_VIDEO_SOURCE_PATH)).expanduser().resolve()

    for i in range(from_step):
        if job.steps[i].status == "pending":
            job.steps[i].status = "skipped"

    current_video = job.source

    # ── Modal path for steps 0-2 ──────────────────────────────────────────────
    if job.use_modal and from_step <= 2:
        # Resolve current_video from previous steps if resuming
        if from_step >= 1:
            nv = job.files.get("no_silence", "")
            if nv and Path(nv).exists():
                current_video = nv

        current_video, ass_path, txt_path = await _run_modal_steps(
            job, from_step, current_video, d, stem
        )
        if job.status == "error":
            return

        job.files["final_video"] = current_video
        await _run_llm_and_upload(job, txt_path, current_video, max(from_step, 3))
        return

    # ── Local path for steps 0-2 ──────────────────────────────────────────────
    if from_step <= 0:
        s0 = job.steps[0]
        if job.do_remove_silence:
            s0.start_time = time.time()
            s0.status = "running"
            s0.progress = 0.0
            out_path = str(d / f"{stem}_nosilence.mp4")
            if remove_silence_simple is not None:
                def _prog0(pct, _): s0.progress = round(pct, 1)
                try:
                    await asyncio.to_thread(remove_silence_simple, job.source, out_path, -65.0, _prog0)
                    rc = 0
                except Exception as exc:
                    s0.output = str(exc); rc = 1
            else:
                rc, _ = await _run(s0, _yt(), "remove-silence", job.source, "-o", out_path)
            if rc != 0:
                s0.end_time = time.time(); s0.status = "error"; job.status = "error"; _save_meta(job); return
            duration = _get_video_duration(out_path)
            if duration > 180:
                s0.end_time = time.time(); s0.status = "error"
                s0.output += f"\n⏱ Video is {duration:.0f}s — exceeds 180s limit for YouTube Shorts."
                job.status = "error"; _save_meta(job); return
            s0.end_time = time.time(); s0.status = "done"; s0.progress = 100
            s0.output += f"\n⏱ Duration: {duration:.0f}s"
            current_video = out_path
            job.files["no_silence"] = out_path
        else:
            s0.status = "skipped"
        _save_meta(job)
    else:
        nv = job.files.get("no_silence", "")
        if nv and Path(nv).exists():
            current_video = nv

    ass_path = str(d / f"{stem}.ass")
    txt_path = str(d / f"{stem}_transcript.txt")

    if from_step <= 1:
        s1 = job.steps[1]
        s1.start_time = time.time()
        s1.status = "running"
        s1.progress = 0.0

        if generate_karaoke_ass is not None:
            if job.simple_transcript:
                try:
                    await asyncio.to_thread(
                        generate_karaoke_ass, current_video, ass_path,
                        job.language, job.model, 96, 35, None,
                    )
                    rc = 0
                except Exception as exc:
                    s1.output = str(exc); rc = 1
            else:
                s1.progress = 0.0

                def _prog1(pct, _):
                    if pct > (s1.progress or 0):
                        s1.progress = round(pct, 1)

                video_dur = _get_video_duration(current_video)
                expected_secs = max(video_dur * 7, 60)

                t1_task = asyncio.create_task(
                    asyncio.to_thread(
                        generate_karaoke_ass, current_video, ass_path,
                        job.language, job.model, 96, 35, _prog1,
                    )
                )
                t1_start = time.time()
                while not t1_task.done():
                    elapsed = time.time() - t1_start
                    est_pct = min(90.0, elapsed / expected_secs * 100)
                    if est_pct > (s1.progress or 0):
                        s1.progress = round(est_pct, 1)
                    await asyncio.sleep(3)

                try:
                    await t1_task
                    rc = 0
                except Exception as exc:
                    s1.output = str(exc); rc = 1
        else:
            rc, _ = await _run(
                s1, _yt(), "extract-transcript", current_video,
                "-o", ass_path, "-l", job.language, "-m", job.model,
            )
        if rc != 0:
            s1.end_time = time.time(); s1.status = "error"; job.status = "error"; _save_meta(job); return
        s1.end_time = time.time()
        elapsed_s = round(s1.end_time - s1.start_time, 1)
        mode_label = "simple" if job.simple_transcript else "advanced"
        s1.output = f"Done in {elapsed_s}s [{mode_label} mode]"
        s1.status = "done"; s1.progress = 100
        plain = _ass_to_plain_text(ass_path)
        with open(txt_path, "w", encoding="utf-8") as _f:
            _f.write(plain)
        job.files["transcript"] = ass_path
        job.files["transcript_txt"] = txt_path
        _save_meta(job)
    else:
        ass_path = job.files.get("transcript") or ass_path
        txt_path = job.files.get("transcript_txt") or txt_path
        if not Path(txt_path).exists() and Path(ass_path).exists():
            plain = _ass_to_plain_text(ass_path)
            with open(txt_path, "w", encoding="utf-8") as _f:
                _f.write(plain)

    if from_step <= 2:
        s2 = job.steps[2]
        if job.do_burn_subtitles:
            s2.start_time = time.time()
            s2.status = "running"
            out_path = str(d / f"{stem}_subtitled.mp4")
            if burn_ass_subtitles is not None:
                def _prog2(pct, _): s2.progress = pct
                try:
                    await asyncio.to_thread(burn_ass_subtitles, current_video, ass_path, out_path, 96, _prog2)
                    rc = 0
                except Exception as exc:
                    s2.output = str(exc); rc = 1
            else:
                rc, _ = await _run(
                    s2, _yt(), "burn-subtitles", current_video, ass_path, "-o", out_path
                )
            if rc != 0:
                s2.end_time = time.time(); s2.status = "error"; job.status = "error"; _save_meta(job); return
            s2.end_time = time.time(); s2.status = "done"; s2.progress = 100
            current_video = out_path
            job.files["subtitled"] = out_path
        else:
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

        rc, title_out = await _run(s3, _pr(), "apply", job.prompt_title, f"transcript=@{transcript_path}")
        if rc != 0:
            s3.end_time = time.time(); s3.status = "error"; job.status = "error"; _save_meta(job); return

        proc = await asyncio.create_subprocess_exec(
            _pr(), "apply", job.prompt_summary, f"transcript=@{transcript_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

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

        safe_name = _sanitize_filename(job.title)
        ext = Path(final_video).suffix or ".mp4"
        renamed_path = str(Path(final_video).parent / f"{safe_name}{ext}")
        if Path(final_video).resolve() != Path(renamed_path).resolve():
            if not Path(renamed_path).exists():
                os.rename(final_video, renamed_path)
            final_video = renamed_path
            job.files["final_video"] = final_video

        s3.output = f"Title: {job.title[:80]}"
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
        job.end_time = time.time()
        job.status = "done"
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
        if rc != 0:
            s4.end_time = time.time(); s4.status = "error"; job.status = "error"; _save_meta(job); return

        s4.end_time = time.time(); s4.status = "done"
        watch_url = url_out.strip()
        video_id = _extract_video_id(watch_url)
        if video_id:
            job.video_url = f"https://www.youtube.com/shorts/{video_id}"
            job.studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
        else:
            job.video_url = watch_url
            job.studio_url = ""
        job.end_time = time.time()
        job.status = "done"
        _save_meta(job)

    await _run_post_publish_step(job, final_video)


async def _run_post_publish_step(job: Job, final_video: str) -> None:
    """Run step 5 (post-publish script). Sets job.status='error' on failure."""
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
    _save_meta(job)
