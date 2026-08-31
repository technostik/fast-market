from __future__ import annotations

import asyncio
import json
import shutil
import time
import traceback
import wave
from pathlib import Path

from ..storyboard.models import (
    ProjectState, Chapter, Scene, StepState,
    SCENE_STEPS, GLOBAL_STEPS, GLOBAL_TO_SCENE_STEP,
)
from ..storyboard.pipeline import (
    _run,
    _run_scene_step, _run_scene_from,
    _assemble_chapter, _assemble_final,
    _find_scene, _find_chapter_for_scene,
    _sound,
)


# Voice-mode source steps (provided by the voice file, never re-generated).
_SOURCE_STEPS = ("gen_transcript", "gen_audio")

# Voice-mode re-runnable scene steps (image prompt -> image -> clip).
_VOICE_SCENE_STAGES = [
    ("image_prompt", "gen_image_prompt"),
    ("image", "gen_image"),
    ("clip", "assemble_clip"),
]


# ── In-memory job tracker (independent of storyboard tab) ──────────────────────

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


def _log_error_to_console(state: ProjectState, summary: str, tb: str = "") -> None:
    state.console_log.append(
        {"t": time.time(), "cmd": summary, "output": tb[-3000:], "rc": 1}
    )


def start_pipeline(
    state: ProjectState,
    state_path: str | Path,
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
    if _current_task is not None and not _current_task.done():
        raise RuntimeError("Pipeline already running")
    _current_state = state
    state_path = Path(state_path)

    async def coro():
        try:
            await _run_pipeline(
                state, state_path, config,
                from_global_step=from_global_step,
                only_global_step=only_global_step,
                scene_id=scene_id,
                from_step=from_step,
                only_step=only_step,
                only_scene=only_scene,
            )
        except asyncio.CancelledError:
            state.parse_step.status = "error"
            _log_error_to_console(state, "Pipeline cancelled", "")
            state.save(state_path)
        except Exception:
            tb = traceback.format_exc()
            _log_error_to_console(state, "Pipeline failed", tb)
            state.save(state_path)
        finally:
            _current_state = None

    _current_task = asyncio.create_task(coro())


# ── Main pipeline logic ───────────────────────────────────────────────────────


def _reset_voice_step(sc: Scene, from_step: str) -> None:
    """Reset from_step and everything downstream, but never touch the
    source-provided steps (transcript / audio)."""
    idx = list(SCENE_STEPS).index(from_step)
    affected = SCENE_STEPS[idx:]
    for step_name in affected:
        if step_name in _SOURCE_STEPS:
            continue
        sc.steps[step_name] = StepState()


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
    # Single-scene re-run.
    if scene_id and from_step:
        sc = _find_scene(state, scene_id)
        if sc is None:
            raise ValueError(f"Scene not found: {scene_id}")
        _reset_voice_step(sc, from_step)
        state.save(state_path)
        if only_step:
            await _run_scene_step(state, state_path, config, sc, from_step)
            return
        await _run_scene_from(state, state_path, config, sc, from_step)
        if only_scene:
            return
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

    # Run only ONE global step.
    if only_global_step:
        if only_global_step in ("parse", "segment"):
            state.parse_step = StepState()
            state.save(state_path)
            await _ingest_voice(state, state_path, config)
            return
        if only_global_step in _SOURCE_STEPS:
            # Source steps are provided by the voice file — nothing to run.
            return
        if only_global_step in GLOBAL_TO_SCENE_STEP:
            skey = GLOBAL_TO_SCENE_STEP[only_global_step]
            if skey in _SOURCE_STEPS:
                return
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

    # Global step re-run (all scenes from that stage, continuing to end).
    from_idx = GLOBAL_STEPS.index(from_global_step) if from_global_step else 0
    if from_global_step:
        if from_idx == 0:
            state.parse_step = StepState()
        first_skey = next(
            (skey for gstep, skey in _VOICE_SCENE_STAGES
             if GLOBAL_STEPS.index(gstep) >= from_idx),
            None,
        )
        if first_skey is not None:
            for ch in state.chapters:
                for sc in ch.scenes:
                    _reset_voice_step(sc, first_skey)
        if from_idx <= GLOBAL_STEPS.index("chapter"):
            for ch in state.chapters:
                ch.merge_step = StepState()
                ch.chapter_file = None
        if from_idx <= GLOBAL_STEPS.index("final"):
            state.final_step = StepState()
            state.final_file = None
        state.save(state_path)

    # Stage 0: segment + ingest (only if not already done).
    if from_idx <= 0:
        if state.parse_step.status != "done":
            await _ingest_voice(state, state_path, config)
            if state.parse_step.status != "done":
                return

    # Stages: image_prompt -> image -> clip.
    for gstep, skey in _VOICE_SCENE_STAGES:
        gidx = GLOBAL_STEPS.index(gstep)
        if from_idx > gidx:
            continue
        for ch in state.chapters:
            for sc in ch.scenes:
                if sc.steps[skey].status == "done":
                    continue
                await _run_scene_step(state, state_path, config, sc, skey)
                if sc.steps[skey].status != "done":
                    return

    # Chapter merges.
    if from_idx <= GLOBAL_STEPS.index("chapter"):
        for ch in state.chapters:
            if ch.merge_step.status == "done":
                continue
            await _assemble_chapter(state, state_path, config, ch)
            if ch.merge_step.status != "done":
                return

    # Final merge.
    if from_idx <= GLOBAL_STEPS.index("final"):
        if state.final_step.status != "done":
            await _assemble_final(state, state_path, config)


# ── Voice ingestion (replaces storyboard's markdown parse) ────────────────────


async def _ingest_voice(state: ProjectState, state_path: Path, config: dict) -> None:
    s = state.parse_step
    s.status = "running"
    s.start_time = time.time()
    s.output = ""
    state.save(state_path)

    workdir = Path(state.workdir)
    segs_dir = workdir / "segments"
    segs_dir.mkdir(parents=True, exist_ok=True)

    if state.segments_json:
        sj = Path(state.segments_json).expanduser()
        if not sj.exists():
            s.status = "error"
            s.output = f"[error] segments_json not found: {sj}"
            s.end_time = time.time()
            state.save(state_path)
            return
        data = json.loads(sj.read_text(encoding="utf-8"))
        src_dir = sj.parent
        s.output = f"Using provided segments: {sj}"
        state.save(state_path)
    else:
        voice = state.voice_file
        if not voice or not Path(voice).expanduser().exists():
            s.status = "error"
            s.output = "[error] No voice file present — pick one or provide segments.json."
            s.end_time = time.time()
            state.save(state_path)
            return
        cmd = [
            _sound(), "segment", str(Path(voice).expanduser()),
            "--output-dir", str(segs_dir),
            "--engine", config.get("transcript_engine", "whisperx"),
            "--model", config.get("transcript_model", "medium"),
            "--language", config.get("language", "en"),
            "--min-segment", str(config.get("segment_min", 10)),
            "--max-segment", str(config.get("segment_max", 30)),
            "--silence", str(config.get("segment_silence", 0.6)),
            "--format", "json",
        ]
        rc = await _run(s, *cmd, log_to=state)
        if rc != 0:
            s.status = "error"
            s.end_time = time.time()
            state.save(state_path)
            return
        data = json.loads((segs_dir / "segments.json").read_text(encoding="utf-8"))
        src_dir = segs_dir

    segs = data.get("segments", [])
    if not segs:
        s.status = "error"
        s.output = "[error] No segments produced by transcription."
        s.end_time = time.time()
        state.save(state_path)
        return

    state.chapters = []
    ch = Chapter(id="ch00", title="voice", scenes=[])
    scene_base = workdir / "chapters" / "ch00" / "scenes"

    for i, seg in enumerate(segs):
        sc_id = f"ch00_sc{i:02d}"
        text = str(seg.get("text", "")).strip()
        sc = Scene(
            id=sc_id,
            title=f"scene_{i}",
            raw_description=text,
            transcript=text,
        )
        audio_rel = seg.get("audio") or f"segments/seg_{i:03d}.wav"
        src_audio = Path(src_dir) / audio_rel
        sc_dir = scene_base / sc_id
        sc_dir.mkdir(parents=True, exist_ok=True)

        dst_audio = sc_dir / "audio.wav"
        if src_audio.exists():
            shutil.copy2(src_audio, dst_audio)
            sc.audio_file = str(dst_audio)
            try:
                with wave.open(str(dst_audio), "rb") as wf:
                    sc.audio_duration = round(wf.getnframes() / wf.getframerate(), 2)
            except Exception:
                pass
        else:
            sc.audio_file = None
            sc.audio_duration = round(float(seg.get("end", 0)) - float(seg.get("start", 0)), 2)

        # Source steps are already satisfied by the voice file.
        sc.steps["gen_transcript"] = StepState(status="done")
        sc.steps["gen_audio"] = StepState(status="done")

        (sc_dir / "description.txt").write_text(text, encoding="utf-8")
        (sc_dir / "transcript.txt").write_text(text, encoding="utf-8")

        ch.scenes.append(sc)

    state.chapters.append(ch)
    s.status = "done"
    s.end_time = time.time()
    s.output = f"Segmented voice into {len(segs)} scenes."
    state.save(state_path)
