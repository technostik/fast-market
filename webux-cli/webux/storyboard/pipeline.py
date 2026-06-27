from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import traceback
from pathlib import Path

from .models import (
    ProjectState, Chapter, Scene, StepState,
    SCENE_STEPS, GLOBAL_STEPS, GLOBAL_TO_SCENE_STEP,
)

# ── In-memory job tracker ─────────────────────────────────────────────────────

_current_task: asyncio.Task | None = None
_current_state: ProjectState | None = None


def is_running() -> bool:
    return _current_task is not None and not _current_task.done()


def get_current_state() -> ProjectState | None:
    return _current_state


def stop_pipeline() -> None:
    global _current_task
    if _current_task and not _current_task.done():
        _current_task.cancel()


# ── Tool path helpers ─────────────────────────────────────────────────────────

def _sound() -> str:
    return shutil.which("sound") or "sound"


def _image_cmd() -> str:
    return shutil.which("image") or "image"


def _prompt_cmd() -> str:
    return shutil.which("prompt") or "prompt"


def _video() -> str:
    return shutil.which("video") or "video"


# ── Subprocess runner ─────────────────────────────────────────────────────────

async def _run(
    step: StepState,
    *cmd: str,
    stdin_data: bytes | None = None,
    log_to: "ProjectState | None" = None,
) -> int:
    cmd_str = " ".join(str(c) for c in cmd)
    if log_to is not None:
        log_to.console_log.append({"t": time.time(), "cmd": cmd_str, "output": "", "rc": None})

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _stream(stream, prefix: str):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if text:
                if step.output:
                    step.output += "\n"
                step.output += f"{prefix}{text}"
                if log_to is not None and log_to.console_log:
                    log_to.console_log[-1]["output"] = step.output[-3000:]

    if stdin_data is not None:
        stdout_bytes, stderr_bytes = await proc.communicate(stdin_data)
        if stdout_bytes:
            for line in stdout_bytes.decode(errors="replace").splitlines():
                if line.strip():
                    if step.output:
                        step.output += "\n"
                    step.output += line
        if stderr_bytes:
            for line in stderr_bytes.decode(errors="replace").splitlines():
                if line.strip():
                    if step.output:
                        step.output += "\n"
                    step.output += f"[err] {line}"
        rc = proc.returncode or 0
        if log_to is not None and log_to.console_log:
            log_to.console_log[-1].update({"output": step.output[-3000:], "rc": rc})
        return rc

    await asyncio.gather(
        _stream(proc.stdout, ""),
        _stream(proc.stderr, "[err] "),
        proc.wait(),
    )
    rc = proc.returncode or 0
    if log_to is not None and log_to.console_log:
        log_to.console_log[-1].update({"output": step.output[-3000:], "rc": rc})
    if len(getattr(log_to, "console_log", [])) > 200:
        log_to.console_log = log_to.console_log[-200:]
    return rc


def _last_line(step: StepState) -> str:
    lines = [l for l in step.output.splitlines() if l.strip()]
    return lines[-1] if lines else ""


# ── Pipeline safe wrapper ──────────────────────────────────────────────────────

async def _run_safely(coro, state: ProjectState, state_path: Path) -> None:
    global _current_task
    try:
        await coro
    except asyncio.CancelledError:
        # Mark any running step as cancelled
        _mark_running_steps_cancelled(state)
        state.save(state_path)
    except Exception as exc:
        traceback.print_exc()
        err_text = f"[error] {type(exc).__name__}: {exc}"
        _mark_running_steps_error(state, err_text)
        state.save(state_path)


def _mark_running_steps_cancelled(state: ProjectState) -> None:
    for step in _all_steps(state):
        if step.status == "running":
            step.status = "pending"
            step.end_time = time.time()


def _mark_running_steps_error(state: ProjectState, msg: str) -> None:
    for step in _all_steps(state):
        if step.status == "running":
            step.status = "error"
            step.end_time = time.time()
            step.output += f"\n{msg}" if step.output else msg


def _all_steps(state: ProjectState):
    yield state.parse_step
    for ch in state.chapters:
        for sc in ch.scenes:
            for s in sc.steps.values():
                yield s
        yield ch.merge_step
    yield state.final_step


# ── Public entry point ────────────────────────────────────────────────────────

def start_pipeline(
    state: ProjectState,
    state_path: Path,
    config: dict,
    *,
    from_global_step: str | None = None,
    only_global_step: str | None = None,
    scene_id: str | None = None,
    from_step: str | None = None,
    only_step: bool = False,
    only_scene: bool = False,
) -> None:
    global _current_task, _current_state
    if is_running():
        raise RuntimeError("Pipeline already running")
    _current_state = state
    coro = _run_pipeline(state, state_path, config,
                         from_global_step=from_global_step,
                         only_global_step=only_global_step,
                         scene_id=scene_id,
                         from_step=from_step,
                         only_step=only_step,
                         only_scene=only_scene)
    _current_task = asyncio.create_task(_run_safely(coro, state, state_path))


# ── Main pipeline logic ───────────────────────────────────────────────────────

async def _run_pipeline(
    state: ProjectState,
    state_path: Path,
    config: dict,
    *,
    from_global_step: str | None = None,
    only_global_step: str | None = None,
    scene_id: str | None = None,
    from_step: str | None = None,
    only_step: bool = False,
    only_scene: bool = False,
) -> None:
    """Run the full pipeline or a partial re-run."""

    # Single-scene mode: rerunStep (only_step) or rerunScene (only_scene or cascade)
    if scene_id and from_step:
        sc = _find_scene(state, scene_id)
        if sc is None:
            raise ValueError(f"Scene not found: {scene_id}")
        sc.reset_from_step(from_step)
        state.save(state_path)
        if only_step:
            # Run exactly this one step and stop
            await _run_scene_step(state, state_path, config, sc, from_step)
            return
        await _run_scene_from(state, state_path, config, sc, from_step)
        if only_scene:
            # Stay within the scene — caller must trigger chapter/final separately
            return
        # Full cascade: re-run chapter merge and final merge downstream
        ch = _find_chapter_for_scene(state, scene_id)
        if ch:
            ch.merge_step = StepState()
            ch.chapter_file = None
            state.save(state_path)
            await _assemble_chapter(state, state_path, config, ch)
        state.final_step = StepState()
        state.final_file = None
        state.save(state_path)
        await _assemble_final(state, state_path, config)
        return

    # Run only ONE global step (step-by-step mode)
    if only_global_step:
        if only_global_step == "parse":
            state.parse_step = StepState()
            state.save(state_path)
            await _parse_script(state, state_path, config)
            return
        if only_global_step in GLOBAL_TO_SCENE_STEP:
            skey = GLOBAL_TO_SCENE_STEP[only_global_step]
            for ch in state.chapters:
                for sc in ch.scenes:
                    sc.steps[skey] = StepState()
            state.save(state_path)
            for ch in state.chapters:
                for sc in ch.scenes:
                    await _run_scene_step(state, state_path, config, sc, skey)
                    if sc.steps[skey].status != "done":
                        return
            return
        if only_global_step == "chapter":
            for ch in state.chapters:
                ch.merge_step = StepState()
                ch.chapter_file = None
            state.save(state_path)
            for ch in state.chapters:
                await _assemble_chapter(state, state_path, config, ch)
            return
        if only_global_step == "final":
            state.final_step = StepState()
            state.final_file = None
            state.save(state_path)
            await _assemble_final(state, state_path, config)
            return

    # Global step re-run (all scenes from that stage, continuing to end)
    from_idx = GLOBAL_STEPS.index(from_global_step) if from_global_step else 0

    # "Run from X": reset the boundary step and ALL downstream steps so they re-run.
    # "Run remaining" (no from_global_step): no reset — only runs pending steps.
    if from_global_step:
        if from_idx == 0:
            state.parse_step = StepState()
        _scene_stages_ordered = [
            ("transcript", "gen_transcript"), ("image_prompt", "gen_image_prompt"),
            ("audio", "gen_audio"), ("image", "gen_image"), ("clip", "assemble_clip"),
        ]
        first_scene_skey = next(
            (skey for gstep, skey in _scene_stages_ordered
             if GLOBAL_STEPS.index(gstep) >= from_idx),
            None,
        )
        if first_scene_skey is not None:
            for ch in state.chapters:
                for sc in ch.scenes:
                    sc.reset_from_step(first_scene_skey)
        if from_idx <= GLOBAL_STEPS.index("chapter"):
            for ch in state.chapters:
                ch.merge_step = StepState()
                ch.chapter_file = None
        if from_idx <= GLOBAL_STEPS.index("final"):
            state.final_step = StepState()
            state.final_file = None
        state.save(state_path)

    # Stage 0: parse
    if from_idx <= 0:
        if state.parse_step.status != "done":
            await _parse_script(state, state_path, config)
            if state.parse_step.status != "done":
                return

    # Stages 1-5: per-scene steps
    scene_stages = [
        ("transcript", "gen_transcript"),
        ("image_prompt", "gen_image_prompt"),
        ("audio", "gen_audio"),
        ("image", "gen_image"),
        ("clip", "assemble_clip"),
    ]
    for gstep, skey in scene_stages:
        gidx = GLOBAL_STEPS.index(gstep)
        if from_idx > gidx:
            continue
        for ch in state.chapters:
            for sc in ch.scenes:
                if sc.steps[skey].status == "done":
                    continue
                await _run_scene_step(state, state_path, config, sc, skey)
                if sc.steps[skey].status != "done":
                    return  # stop on first error

    # Stage 6: chapter merges
    if from_idx <= GLOBAL_STEPS.index("chapter"):
        for ch in state.chapters:
            if ch.merge_step.status == "done":
                continue
            await _assemble_chapter(state, state_path, config, ch)
            if ch.merge_step.status != "done":
                return

    # Stage 7: final merge
    if from_idx <= GLOBAL_STEPS.index("final"):
        if state.final_step.status != "done":
            await _assemble_final(state, state_path, config)


async def _run_scene_from(
    state: ProjectState,
    state_path: Path,
    config: dict,
    sc: Scene,
    from_step: str,
) -> None:
    start_idx = list(SCENE_STEPS).index(from_step)
    for skey in SCENE_STEPS[start_idx:]:
        if sc.steps[skey].status == "done":
            continue
        await _run_scene_step(state, state_path, config, sc, skey)
        if sc.steps[skey].status != "done":
            return


async def _run_scene_step(
    state: ProjectState,
    state_path: Path,
    config: dict,
    sc: Scene,
    skey: str,
) -> None:
    if skey == "gen_transcript":
        await _gen_transcript(state, state_path, config, sc)
    elif skey == "gen_image_prompt":
        await _gen_image_prompt(state, state_path, config, sc)
    elif skey == "gen_audio":
        await _gen_audio(state, state_path, config, sc)
    elif skey == "gen_image":
        await _gen_image(state, state_path, config, sc)
    elif skey == "assemble_clip":
        await _assemble_clip(state, state_path, config, sc)


# ── Individual step implementations ──────────────────────────────────────────

def _clean_for_reparse(state: ProjectState) -> None:
    """Remove all files generated by a previous pipeline run."""
    chapters_dir = Path(state.workdir) / "chapters"
    if chapters_dir.exists():
        shutil.rmtree(chapters_dir)
    final = Path(state.workdir) / "final.mp4"
    if final.exists():
        final.unlink()
    state.chapters = []
    state.final_step = StepState()
    state.final_file = None


async def _parse_script(state: ProjectState, state_path: Path, config: dict) -> None:
    s = state.parse_step
    s.status = "running"
    s.start_time = time.time()
    s.output = ""
    if state.chapters:
        _clean_for_reparse(state)
    state.save(state_path)

    script_text = state.script_text
    if not script_text.strip():
        s.status = "error"
        s.output = "[error] Script text is empty — paste your script first"
        s.end_time = time.time()
        state.save(state_path)
        return

    # Write script to file so prompt CLI can reference it as a named parameter
    workdir = Path(state.workdir)
    script_file = workdir / "script.txt"
    script_file.write_text(script_text, encoding="utf-8")

    # Resolve config placeholders first, then escape remaining { } for prompt CLI.
    template = _resolve_prompt(config["prompts"]["story_breakdown"], config)
    prompt_with_placeholder = template.replace("{", "{{").replace("}", "}}") + "{content}"

    rc = await _run(s, _prompt_cmd(), "apply", prompt_with_placeholder,
                    "--format", "text",
                    f"content=@{script_file}",
                    log_to=state)
    if rc != 0:
        s.status = "error"
        s.end_time = time.time()
        state.save(state_path)
        return

    # Extract JSON from LLM response (may include markdown fences)
    raw = s.output
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if not json_match:
        s.status = "error"
        s.output += "\n[error] No JSON found in LLM response"
        s.end_time = time.time()
        state.save(state_path)
        return

    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError as exc:
        s.status = "error"
        s.output += f"\n[error] Failed to parse JSON: {exc}"
        s.end_time = time.time()
        state.save(state_path)
        return

    chapters = data.get("chapters", [])
    if not chapters:
        s.status = "error"
        s.output += "\n[error] LLM returned no chapters"
        s.end_time = time.time()
        state.save(state_path)
        return

    state.chapters = []
    for ci, ch_data in enumerate(chapters):
        ch_id = f"ch{ci:02d}"
        ch_title = _slugify(ch_data.get("title", f"chapter_{ci}"))
        scenes = []
        for si, sc_data in enumerate(ch_data.get("scenes", [])):
            sc_id = f"{ch_id}_sc{si:02d}"
            scenes.append(Scene(
                id=sc_id,
                title=_slugify(sc_data.get("title", f"scene_{si}")),
                raw_description=sc_data.get("description", ""),
            ))
        state.chapters.append(Chapter(id=ch_id, title=ch_title, scenes=scenes))

    # Create directory structure
    for ch in state.chapters:
        for sc in ch.scenes:
            scene_dir = Path(state.workdir) / "chapters" / ch.id / "scenes" / sc.id
            scene_dir.mkdir(parents=True, exist_ok=True)
            (scene_dir / "description.txt").write_text(sc.raw_description, encoding="utf-8")

    s.status = "done"
    s.end_time = time.time()
    total_scenes = sum(len(ch.scenes) for ch in state.chapters)
    s.output = (
        f"Parsed {len(state.chapters)} chapters, {total_scenes} scenes.\n"
        + "\n".join(
            f"  Ch{i+1}: {ch.title} ({len(ch.scenes)} scenes)"
            for i, ch in enumerate(state.chapters)
        )
    )
    state.save(state_path)


async def _gen_transcript(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    step = sc.steps["gen_transcript"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    scene_dir = _scene_dir(state, sc)
    template = _resolve_prompt(config["prompts"]["scene_transcript"], config)
    prompt_with_placeholder = template.replace("{", "{{").replace("}", "}}") + "{content}"

    description_file = scene_dir / "description.txt"
    rc = await _run(step, _prompt_cmd(), "apply", prompt_with_placeholder,
                    "--format", "text",
                    f"content=@{description_file}",
                    log_to=state)
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    sc.transcript = step.output.strip()
    transcript_file = scene_dir / "transcript.txt"
    transcript_file.write_text(sc.transcript, encoding="utf-8")
    step.output_file = str(transcript_file)
    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _gen_image_prompt(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    step = sc.steps["gen_image_prompt"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    scene_dir = _scene_dir(state, sc)
    content = sc.raw_description
    if sc.transcript:
        content += f"\n\nNarration text:\n{sc.transcript}"
    input_file = scene_dir / "image_prompt_input.txt"
    input_file.write_text(content, encoding="utf-8")

    template = _resolve_prompt(config["prompts"]["scene_image_prompt"], config)
    prompt_with_placeholder = template.replace("{", "{{").replace("}", "}}") + "{content}"

    rc = await _run(step, _prompt_cmd(), "apply", prompt_with_placeholder,
                    "--format", "text",
                    f"content=@{input_file}",
                    log_to=state)
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    sc.image_prompt = step.output.strip()
    prompt_file = scene_dir / "image_prompt.txt"
    prompt_file.write_text(sc.image_prompt, encoding="utf-8")
    step.output_file = str(prompt_file)
    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _gen_audio(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    step = sc.steps["gen_audio"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    scene_dir = _scene_dir(state, sc)
    transcript_file = scene_dir / "transcript.txt"
    if not transcript_file.exists():
        transcript_file.write_text(sc.transcript or sc.raw_description, encoding="utf-8")

    audio_out = scene_dir / "audio.wav"
    tts_engine = config.get("tts_engine", "kokoro")
    lang = config.get("language", "en")

    rc = await _run(
        step,
        _sound(), "speak",
        "--file", str(transcript_file),
        "--engine", tts_engine,
        "--language", lang,
        "--output", str(audio_out),
        log_to=state,
    )
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    sc.audio_file = str(audio_out)
    step.output_file = str(audio_out)
    try:
        import wave as _wave
        with _wave.open(str(audio_out), "rb") as wf:
            sc.audio_duration = round(wf.getnframes() / wf.getframerate(), 1)
    except Exception:
        pass
    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _gen_image(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    step = sc.steps["gen_image"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    scene_dir = _scene_dir(state, sc)
    image_engine = config.get("image_engine", "flux2cloud")
    image_size = config.get("image_size", "landscape")
    image_seed = config.get("image_seed")    # None = random
    image_steps = config.get("image_steps")  # None = engine default
    draft_mode = config.get("draft_mode", False)
    prompt_text = sc.image_prompt or sc.raw_description

    cmd: list[str] = [
        _image_cmd(), "generate", prompt_text,
        "--engine", image_engine,
        "--output-dir", str(scene_dir),
        "--format", "json",
    ]
    if draft_mode:
        cmd.extend(["--width", "512", "--height", "288"])
        cmd.extend(["--steps", str(config.get("draft_steps", 1))])
    else:
        cmd.extend(["--size", image_size])
        if image_steps is not None:
            cmd.extend(["--steps", str(image_steps)])
    if image_seed is not None:
        cmd.extend(["--seed", str(image_seed)])

    rc = await _run(step, *cmd, log_to=state)
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    # Parse image path from JSON output
    image_file = _extract_json_path(step.output)
    if image_file and Path(image_file).exists():
        sc.image_file = image_file
        step.output_file = image_file
    else:
        # Fallback: find most recent PNG/JPEG in scene_dir
        imgs = sorted(scene_dir.glob("*.png")) + sorted(scene_dir.glob("*.jpg"))
        if imgs:
            sc.image_file = str(imgs[-1])
            step.output_file = sc.image_file

    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _assemble_clip(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    step = sc.steps["assemble_clip"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    scene_dir = _scene_dir(state, sc)
    clip_out = scene_dir / "clip.mp4"

    if not sc.image_file or not Path(sc.image_file).exists():
        step.status = "error"
        step.output = "[error] No image file found — run gen_image first"
        step.end_time = time.time()
        state.save(state_path)
        return
    if not sc.audio_file or not Path(sc.audio_file).exists():
        step.status = "error"
        step.output = "[error] No audio file found — run gen_audio first"
        step.end_time = time.time()
        state.save(state_path)
        return

    fps = config.get("fps", 24)
    motion = config.get("ken_burns_motion", "random")

    rc = await _run(
        step,
        _video(), "assemble",
        sc.image_file, sc.audio_file,
        "--output", str(clip_out),
        "--motion", motion,
        "--fps", str(fps),
        log_to=state,
    )
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    sc.clip_file = str(clip_out)
    step.output_file = str(clip_out)
    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _assemble_chapter(
    state: ProjectState, state_path: Path, config: dict, ch: Chapter
) -> None:
    step = ch.merge_step
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    clip_files = [sc.clip_file for sc in ch.scenes if sc.clip_file and Path(sc.clip_file).exists()]
    missing = [sc.id for sc in ch.scenes if not sc.clip_file or not Path(sc.clip_file or "").exists()]
    step.output = f"Clips found: {len(clip_files)}/{len(ch.scenes)}"
    if missing:
        step.output += f"\nMissing clip for: {', '.join(missing)}"

    if not clip_files:
        step.status = "error"
        step.output += "\n[error] No scene clips found for this chapter"
        step.end_time = time.time()
        state.save(state_path)
        return

    ch_dir = Path(state.workdir) / "chapters" / ch.id
    ch_dir.mkdir(parents=True, exist_ok=True)
    chapter_out = ch_dir / "chapter.mp4"
    if chapter_out.exists():
        chapter_out.unlink()

    try:
        if len(clip_files) == 1:
            import shutil as _shutil
            step.output += f"\nCopying {Path(clip_files[0]).name} → {chapter_out.name}"
            _shutil.copy2(clip_files[0], str(chapter_out))
            step.output += "\nCopy done"
        else:
            step.output += f"\nConcat {len(clip_files)} clips → {chapter_out.name}"
            await _moviepy_concat(clip_files, str(chapter_out))
            step.output += "\nConcat done"
    except Exception as exc:
        step.status = "error"
        step.output += f"\n[error] {type(exc).__name__}: {exc}"
        step.end_time = time.time()
        state.save(state_path)
        return

    if chapter_out.exists():
        ch.chapter_file = str(chapter_out)
        step.output_file = str(chapter_out)
        step.status = "done"
    else:
        step.status = "error"
        step.output += "\n[error] Chapter file was not created after write"
    step.end_time = time.time()
    state.save(state_path)


async def _assemble_final(
    state: ProjectState, state_path: Path, config: dict
) -> None:
    step = state.final_step
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    all_ch = [(ch.id, ch.chapter_file) for ch in state.chapters]
    step.output = f"Chapters: {len(all_ch)}"
    for ch_id, cf in all_ch:
        exists = Path(cf).exists() if cf else False
        step.output += f"\n  {ch_id}: {cf or '(none)'} {'✓' if exists else '✗ MISSING'}"

    chapter_files = [cf for _, cf in all_ch if cf and Path(cf).exists()]
    if not chapter_files:
        step.status = "error"
        step.output += "\n[error] No chapter files found on disk"
        step.end_time = time.time()
        state.save(state_path)
        return

    final_out = Path(state.workdir) / "final.mp4"
    if final_out.exists():
        final_out.unlink()
        step.output += "\nRemoved old final.mp4"

    try:
        if len(chapter_files) == 1:
            import shutil as _shutil
            step.output += f"\nCopying {Path(chapter_files[0]).name} → final.mp4"
            _shutil.copy2(chapter_files[0], str(final_out))
            step.output += "\nCopy done"
        else:
            step.output += f"\nConcat {len(chapter_files)} chapters → final.mp4"
            await _moviepy_concat(chapter_files, str(final_out))
            step.output += "\nConcat done"
    except Exception as exc:
        step.status = "error"
        step.output += f"\n[error] {type(exc).__name__}: {exc}"
        step.end_time = time.time()
        state.save(state_path)
        return

    if final_out.exists():
        state.final_file = str(final_out)
        step.output_file = str(final_out)
        step.status = "done"
        step.output += f"\nfinal.mp4 written ({final_out.stat().st_size // 1024} KB)"
    else:
        step.status = "error"
        step.output += "\n[error] Final file not found after write — write silently failed"
    step.end_time = time.time()
    state.save(state_path)


async def _moviepy_concat(clip_files: list[str], output: str) -> None:
    """Concatenate video files with moviepy. Raises on failure — caller handles."""
    def _do_concat():
        from moviepy import VideoFileClip, concatenate_videoclips
        import os
        clips = [VideoFileClip(f) for f in clip_files]
        result = concatenate_videoclips(clips)
        temp_audio = os.path.join(os.path.dirname(os.path.abspath(output)), "temp-audio-concat.m4a")
        result.write_videofile(
            output, codec="libx264", audio_codec="aac",
            temp_audiofile=temp_audio, remove_temp=True,
            audio_bitrate="192k", preset="medium", logger=None,
        )
        for c in clips:
            c.close()
        result.close()

    await asyncio.to_thread(_do_concat)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scene_dir(state: ProjectState, sc: Scene) -> Path:
    ch_id = sc.id.rsplit("_sc", 1)[0]
    return Path(state.workdir) / "chapters" / ch_id / "scenes" / sc.id


def _find_scene(state: ProjectState, scene_id: str) -> Scene | None:
    for ch in state.chapters:
        for sc in ch.scenes:
            if sc.id == scene_id:
                return sc
    return None


def _find_chapter_for_scene(state: ProjectState, scene_id: str) -> Chapter | None:
    for ch in state.chapters:
        for sc in ch.scenes:
            if sc.id == scene_id:
                return ch
    return None


def _extract_json_path(text: str) -> str | None:
    json_match = re.search(r"\{[^}]*\"path\"\s*:\s*\"([^\"]+)\"[^}]*\}", text)
    if json_match:
        try:
            d = json.loads(json_match.group(0))
            return d.get("path")
        except json.JSONDecodeError:
            pass
    return None


def _resolve_prompt(template: str, config: dict) -> str:
    """Substitute all known config placeholders before prompt CLI escaping."""
    subs = {
        "lang": config.get("language", "en"),
        "chapter_range": config.get("chapter_range", "2–5"),
        "scene_range": config.get("scene_range", "2–5"),
        "scene_duration": config.get("scene_duration", "15–45 seconds"),
        "narrative_style": config.get("narrative_style", "documentary narration"),
        "image_style": config.get("image_style", "cinematic, dramatic lighting"),
    }
    for k, v in subs.items():
        template = template.replace(f"{{{k}}}", str(v))
    return template


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:40] or "untitled"
