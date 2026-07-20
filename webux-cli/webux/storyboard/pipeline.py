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
from .config import load_storyboard_config, save_storyboard_config

# Rough spoken-word rate used only to translate a target duration (seconds) into a
# word-count budget for the LLM in the narrate prompt. Not used for anything precise —
# actual scene timing always comes from the real TTS-rendered audio_duration.
WORDS_PER_SECOND = 2.5

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


def _set_current_task(task: asyncio.Task) -> None:
    """Register a background task so get_current_state()/is_running() track it."""
    global _current_task
    _current_task = task


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
    # Quote args that contain spaces so the logged command matches what actually
    # runs (asyncio passes the list directly to the subprocess — no shell), and is
    # safe to copy-paste into a shell.
    def _fmt(c: str) -> str:
        s = str(c)
        return f'"{s}"' if (" " in s or "\t" in s) else s
    cmd_str = " ".join(_fmt(c) for c in cmd)
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
        tb = traceback.format_exc()
        traceback.print_exc()
        err_text = f"[error] {type(exc).__name__}: {exc}"
        _mark_running_steps_error(state, err_text)
        _log_error_to_console(state, err_text, tb)
        state.save(state_path)


def _log_error_to_console(state: ProjectState, summary: str, tb: str = "") -> None:
    state.console_log.append({
        "t": time.time(),
        "cmd": "pipeline-error",
        "output": f"{summary}\n{tb}".strip(),
        "rc": 1,
    })
    if len(state.console_log) > 200:
        state.console_log = state.console_log[-200:]


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

    # Self-heal: if a generated character already exists in this project, make
    # sure the config flag is on so scene generation uses it (covers characters
    # generated before this auto-enable logic existed).
    if state.character_image and Path(state.character_image).exists() and not config.get("character_enabled"):
        save_storyboard_config({"character_enabled": True})
        config["character_enabled"] = True

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
        if only_global_step == "character":
            if not config.get("character_enabled"):
                state.character_step = StepState()
                state.character_step.status = "skipped"
                state.character_step.output = "Central character disabled in config."
                state.save(state_path)
                return
            state.character_step = StepState()
            state.character_description = ""
            state.character_image = None
            state.save(state_path)
            await _gen_character(
                state, state_path, config,
                use_reference=bool(config.get("character_use_reference")),
            )
            if state.character_image and Path(state.character_image).exists():
                save_storyboard_config({"character_enabled": True})
            return
        if only_global_step == "narrate":
            state.narration_step = StepState()
            state.narration_text = ""
            state.save(state_path)
            await _gen_narration(state, state_path, config)
            return
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
        # Reset the narrate step whenever we run from narrate or earlier, so it
        # regenerates the narration text (e.g. after changing content_mode or
        # target_duration_seconds).
        if from_idx <= GLOBAL_STEPS.index("narrate"):
            state.narration_step = StepState()
            state.narration_text = ""
        # Reset the parse step whenever we run from parse or earlier, so it
        # re-splits the (possibly new) narration (e.g. after changing
        # chapter_range/scene_range, or after narrate re-ran above).
        if from_idx <= GLOBAL_STEPS.index("parse"):
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

    # Stage 0: central character (optional, pre-pipeline)
    char_idx = GLOBAL_STEPS.index("character")
    if config.get("character_enabled") and from_idx <= char_idx:
        if state.character_step.status != "done":
            await _gen_character(
                state, state_path, config,
                use_reference=bool(config.get("character_use_reference")),
            )
            if state.character_step.status != "done":
                return
            if state.character_image and Path(state.character_image).exists():
                save_storyboard_config({"character_enabled": True})

    # Stage 1: narrate (skipped internally when content_mode == "oral_script")
    if from_idx <= GLOBAL_STEPS.index("narrate"):
        if state.narration_step.status != "done":
            await _gen_narration(state, state_path, config)
            if state.narration_step.status != "done":
                return

    # Stage 2: parse (a.k.a. "segment" — cuts the final narration into scenes)
    if from_idx <= GLOBAL_STEPS.index("parse"):
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


def _duration_instruction(config: dict) -> str:
    """Build the {duration_instruction} sub for the narrate prompt.

    target_duration_seconds is None/unset  -> faithful, full-length narration.
    target_duration_seconds is set          -> allowed/expected to condense to fit.
    """
    target = config.get("target_duration_seconds")
    if not target:
        return (
            "Target length: NONE. Write the full, faithful narration of the ENTIRE "
            "article — do not summarize, do not omit sections or arguments. Only adapt "
            "the register from written to spoken; the total length should track the "
            "full article."
        )
    try:
        target = float(target)
    except (TypeError, ValueError):
        return (
            "Target length: NONE. Write the full, faithful narration of the ENTIRE "
            "article — do not summarize, do not omit sections or arguments. Only adapt "
            "the register from written to spoken; the total length should track the "
            "full article."
        )
    target_words = max(20, round(target * WORDS_PER_SECOND))
    return (
        f"Target length: your narration must fit within approximately {int(target)} "
        f"seconds of spoken narration (roughly {target_words} words at a natural pace). "
        "To hit this target, CONDENSE the article: keep its core thesis and structure "
        "intact, but cut secondary examples, digressions, and repetition. Do not pad."
    )


async def _gen_narration(state: ProjectState, state_path: Path, config: dict) -> None:
    """Stage 'narrate': produce ONE continuous, final oral narration text.

    - content_mode == "oral_script": the pasted script is already a finished oral
      script (e.g. produced upstream by a dedicated scriptwriting prompt/pipeline
      that already handled pacing, hooks, callbacks...). We must NOT rewrite it —
      any regeneration here would flatten narrative work already done elsewhere.
      This step is a fast, deterministic pass-through.
    - content_mode == "raw_article" (default): the pasted text is written material
      (e.g. an essay) and needs a real oral adaptation. We call the LLM exactly
      ONCE over the *entire* text so the result is coherent by construction —
      no scene-by-scene blind rewriting, no lost throughline.
    """
    s = state.narration_step
    s.status = "running"
    s.start_time = time.time()
    s.output = ""
    state.save(state_path)

    script_text = state.script_text
    if not script_text.strip():
        s.status = "error"
        s.output = "[error] Script text is empty — paste your script first"
        s.end_time = time.time()
        state.save(state_path)
        return

    workdir = Path(state.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    narration_file = workdir / "narration.txt"

    content_mode = config.get("content_mode", "raw_article")
    if content_mode == "oral_script":
        # Pass-through: the input IS the narration. No LLM call.
        state.narration_text = script_text.strip()
        narration_file.write_text(state.narration_text, encoding="utf-8")
        s.output = (
            "[skipped] content_mode=oral_script — using the pasted script verbatim "
            "as the narration (no rewrite)."
        )
        s.output_file = str(narration_file)
        s.status = "done"
        s.end_time = time.time()
        state.save(state_path)
        return

    script_file = workdir / "script.txt"
    script_file.write_text(script_text, encoding="utf-8")

    rc = await _apply_story_prompt(
        s, state, config, "narrate", script_file,
        extra_subs={"duration_instruction": _duration_instruction(config)},
    )
    if rc != 0:
        s.status = "error"
        s.end_time = time.time()
        state.save(state_path)
        return

    state.narration_text = s.output.strip()
    narration_file.write_text(state.narration_text, encoding="utf-8")
    s.output_file = str(narration_file)
    s.status = "done"
    s.end_time = time.time()
    state.save(state_path)


async def _parse_script(state: ProjectState, state_path: Path, config: dict) -> None:
    s = state.parse_step
    s.status = "running"
    s.start_time = time.time()
    s.output = ""
    if state.chapters:
        _clean_for_reparse(state)
    state.save(state_path)

    narration_text = state.narration_text
    if not narration_text.strip():
        s.status = "error"
        s.output = "[error] No narration text yet — run the 'narrate' step first"
        s.end_time = time.time()
        state.save(state_path)
        return

    # Write the FINAL narration to file so prompt CLI can reference it as a named
    # parameter. This step only cuts this already-final text into scenes — it must
    # not regenerate or rephrase it.
    workdir = Path(state.workdir)
    narration_file = workdir / "narration.txt"
    if not narration_file.exists():
        narration_file.write_text(narration_text, encoding="utf-8")

    rc = await _apply_story_prompt(s, state, config, "story_breakdown", narration_file)
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
            scene = Scene(
                id=sc_id,
                title=_slugify(sc_data.get("title", f"scene_{si}")),
                raw_description=sc_data.get("description", ""),
                # The segment step already cut a near-verbatim excerpt of the final
                # narration — this IS the scene's transcript. No further AI rewriting.
                transcript=(sc_data.get("transcript") or "").strip(),
            )
            if scene.transcript:
                # Pre-complete the "transcript" scene step: segmentation already did
                # the job, no blind per-scene regeneration is needed (or wanted).
                step = scene.steps["gen_transcript"]
                step.status = "done"
                step.start_time = step.end_time = time.time()
                step.output = "[from segment] verbatim excerpt of the final narration."
            scenes.append(scene)
        state.chapters.append(Chapter(id=ch_id, title=ch_title, scenes=scenes))

    # Fail loudly here if the model returned scenes without a verbatim transcript
    # excerpt. Otherwise the empty transcript slips through segmentation and only
    # surfaces later as the confusing "No transcript to confirm" error in the
    # per-scene gen_transcript step. Most common cause: the JSON output was
    # truncated (raise max_tokens on the storyboard-breakdown prompt) or the model
    # omitted/renamed the "transcript" field.
    missing = [
        sc.id
        for ch in state.chapters
        for sc in ch.scenes
        if not sc.transcript.strip()
    ]
    if missing:
        s.status = "error"
        s.output += (
            f"\n[error] Segmentation returned {len(missing)} scene(s) with no "
            f"transcript: {', '.join(missing)}. The model likely truncated its JSON "
            "output or omitted the 'transcript' field. Re-run the 'segment' step "
            "(raise max_tokens on the storyboard-breakdown prompt if the narration "
            "is long), or paste transcripts manually in the scene detail panel."
        )
        s.end_time = time.time()
        state.save(state_path)
        return

    # Create directory structure
    for ch in state.chapters:
        for sc in ch.scenes:
            scene_dir = Path(state.workdir) / "chapters" / ch.id / "scenes" / sc.id
            scene_dir.mkdir(parents=True, exist_ok=True)
            (scene_dir / "description.txt").write_text(sc.raw_description, encoding="utf-8")
            if sc.transcript:
                transcript_file = scene_dir / "transcript.txt"
                transcript_file.write_text(sc.transcript, encoding="utf-8")
                sc.steps["gen_transcript"].output_file = str(transcript_file)

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
    # Soft sanity check: the LLM was instructed to cut the narration verbatim, never
    # to rewrite it. If the concatenated transcripts drift too far in word count from
    # the source narration, it likely paraphrased instead of cutting — warn (don't
    # fail) so it's visible in the step output / console.
    narration_words = len(narration_text.split())
    transcript_words = sum(
        len(sc.transcript.split()) for ch in state.chapters for sc in ch.scenes
    )
    if narration_words > 0:
        drift = abs(transcript_words - narration_words) / narration_words
        if drift > 0.15:
            s.output += (
                f"\n[warn] Scene transcripts total {transcript_words} words vs "
                f"{narration_words} in the narration ({drift:.0%} drift) — the model may "
                "have paraphrased instead of cutting verbatim. Check the scenes."
            )
    state.save(state_path)


async def _gen_character(
    state: ProjectState, state_path: Path, config: dict,
    *,
    use_reference: bool = False,   # load from stored config reference instead of generating
    reedit_description: str | None = None,  # user-provided description override
    force_description: bool = False,  # regenerate description even if one already exists
    gen_character_image: bool = True,  # generate the reference image (False = description only)
) -> None:
    """Generate (or load) the central character: a 3/4 reference image + description.

    Two phases:
      1. Description — auto-generated from the script via the character prompt,
         unless the user supplied one (reedit_description) or one already exists
         (skipped unless force_description).
      2. Image — a 3/4 reference portrait generated from the description.

    Either phase can be skipped: `gen_character_image=False` produces only the
    description; `use_reference=True` loads a stored cross-story reference image
    and marks the step done without generating anything.
    """
    step = state.character_step
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    workdir = Path(state.workdir)

    # 1. Load from a stored cross-story reference if requested.
    if use_reference:
        ref_img = config.get("character_reference_image")
        ref_desc = config.get("character_reference_description", "")
        if ref_img and Path(ref_img).exists():
            dest = workdir / "character.png"
            shutil.copy2(ref_img, dest)
            state.character_image = str(dest)
            # Use the stored description if present, otherwise derive one from the
            # script via the storyboard-character prompt. The description is required
            # for scene image prompts ({character}); a reference image alone with no
            # description means the character is never actually injected into scenes.
            if ref_desc:
                state.character_description = ref_desc
            elif not state.character_description or force_description:
                step.output = (
                    "Loaded stored reference image; no stored description — "
                    "generating one from the script…"
                )
                state.save(state_path)
                script_file = workdir / "script.txt"
                if not script_file.exists():
                    script_file.write_text(state.script_text, encoding="utf-8")
                rc = await _apply_story_prompt(step, state, config, "character", script_file)
                if rc != 0:
                    step.status = "error"
                    step.end_time = time.time()
                    state.save(state_path)
                    return
                state.character_description = step.output.strip()
            step.output = (
                f"Loaded stored reference character.\nDescription: {state.character_description}"
            )
            step.output_file = str(dest)
            step.status = "done"
            step.end_time = time.time()
            state.save(state_path)
            return
        step.output = "[warn] No stored reference found in config — generating instead."

    # 2. Determine the description (auto from script, or user-provided/edited).
    if reedit_description and reedit_description.strip():
        state.character_description = reedit_description.strip()
    elif not state.character_description or force_description:
        # Auto-generate the description from the full script via the character prompt.
        step.output = "Generating character description from script…"
        state.save(state_path)
        script_file = workdir / "script.txt"
        if not script_file.exists():
            script_file.write_text(state.script_text, encoding="utf-8")
        rc = await _apply_story_prompt(step, state, config, "character", script_file)
        if rc != 0:
            step.status = "error"
            step.end_time = time.time()
            state.save(state_path)
            return
        state.character_description = step.output.strip()

    # 3. Optionally stop after the description phase (e.g. "Generate Description" button).
    if not gen_character_image:
        step.output = f"Character description ready.\n{state.character_description}"
        step.status = "done"
        step.end_time = time.time()
        state.save(state_path)
        return

    # 4. Generate the 3/4 reference image from the description.
    image_engine = config.get("image_engine", "flux2cloud")
    char_style = config.get("character_style", "realist")
    if char_style == "free" and config.get("character_style_free"):
        char_style = config.get("character_style_free")
    style_suffix = {
        "cartoon": "franco-belgian comic / cartoon style, clean lines, flat colors",
        "realist": "photorealistic, cinematic lighting, high detail",
    }.get(char_style, char_style)

    char_prompt = (
        f"Character reference sheet, 3/4 front-facing view from head to knees, "
        f"plain neutral solid background, full body visible, no other people, "
        f"no text, no logo. {style_suffix}. "
        f"Subject: {state.character_description}"
    )

    char_out = workdir / "character.png"
    cmd = [
        _image_cmd(), "generate", char_prompt,
        "--engine", image_engine,
        "--output-dir", str(workdir),
        "--size", "square",
        "--format", "json",
    ]
    rc = await _run(step, *cmd, log_to=state)
    if rc != 0:
        step.status = "error"
        step.end_time = time.time()
        state.save(state_path)
        return

    image_file = _extract_json_path(step.output)
    if image_file and Path(image_file).exists():
        # Normalize to a stable name in workdir.
        if Path(image_file) != char_out:
            shutil.copy2(image_file, char_out)
        state.character_image = str(char_out)
        step.output_file = str(char_out)
    else:
        imgs = sorted(workdir.glob("*.png")) + sorted(workdir.glob("*.jpg"))
        if imgs:
            shutil.copy2(imgs[-1], char_out)
            state.character_image = str(char_out)
            step.output_file = str(char_out)

    step.output = f"Character generated.\nDescription: {state.character_description}"
    step.status = "done"
    step.end_time = time.time()
    state.save(state_path)


async def _gen_transcript(
    state: ProjectState, state_path: Path, config: dict, sc: Scene
) -> None:
    """Confirm/persist the scene transcript — no AI call.

    The transcript is produced once, for the whole narration, by the 'segment' step
    (a near-verbatim cut of the final narration text) so that consecutive scenes stay
    coherent. Regenerating a single scene's transcript blindly from a 2-3 sentence
    description (the old behaviour) is exactly what broke the meta-narration, so this
    step is now a deterministic pass-through: it just (re)writes whatever transcript
    the scene currently holds (from segmentation, or from a manual edit via the
    scene detail panel / POST /scene/{id}) to disk and marks the step done.
    """
    step = sc.steps["gen_transcript"]
    step.status = "running"
    step.start_time = time.time()
    step.output = ""
    state.save(state_path)

    if not sc.transcript.strip():
        step.status = "error"
        step.output = (
            "[error] No transcript to confirm — re-run the 'parse' (segment) step, "
            "or paste one manually in the scene detail panel."
        )
        step.end_time = time.time()
        state.save(state_path)
        return

    scene_dir = _scene_dir(state, sc)
    transcript_file = scene_dir / "transcript.txt"
    transcript_file.write_text(sc.transcript, encoding="utf-8")
    step.output = "[confirmed] transcript persisted to disk (no AI rewrite)."
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

    # Choose the image-prompt template based on whether a character is in play.
    # When a central character is active, use the dedicated "with character" prompt
    # (designed to incorporate the reference image); otherwise the plain one.
    # The description can come from the live state OR from a stored reference in
    # config (e.g. a re-opened project that saved a reference but hasn't generated
    # a character in this session yet) — both make the character "active".
    char_desc = state.character_description or config.get("character_reference_description", "")
    # The character is "active" (→ use the with-character template) when enabled AND
    # we have either a description OR a usable reference image. In reference mode the
    # description may be blank; the reference image alone still makes the character
    # present in the scene, so we must not silently fall back to the plain template.
    ref_image = state.character_image or config.get("character_reference_image")
    has_ref_image = bool(ref_image and Path(ref_image).exists())
    char_active = bool(config.get("character_enabled") and (char_desc or has_ref_image))
    prompt_key = "scene_image_prompt_with_character" if char_active else "scene_image_prompt"

    # Inject the central character description as the {character} placeholder when enabled.
    subs = {}
    if char_active:
        subs["character"] = char_desc or "(refer to reference image 0)"

    rc = await _apply_story_prompt(step, state, config, prompt_key, input_file, subs)
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

    # Inject the central character reference image for subject consistency.
    # Prefer the live character image (generated/loaded this session); fall back to
    # the stored cross-story reference in config (reference mode may not have set
    # state.character_image). Either way the "with character" prompt refers to
    # "image 0", so the reference MUST be passed here.
    ref_image = state.character_image or config.get("character_reference_image")
    if config.get("character_enabled") and ref_image and Path(ref_image).exists():
        # The scene image prompt (the dedicated "with character" template) already
        # embeds the character description; we also pass the reference image so the
        # engine keeps the subject visually consistent with the character sheet.
        cmd.extend(["--reference-image", ref_image])
        if config.get("character_strength") is not None:
            cmd.extend(["--strength", str(config.get("character_strength"))])
        step.output += f"\n[character] using reference image: {ref_image} (strength={config.get('character_strength')})\n"

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
            await _moviepy_concat(clip_files, str(chapter_out), transition="none", duration=0)
            step.output += "\nConcat done"
    except Exception as exc:
        tb = traceback.format_exc()
        step.status = "error"
        step.output += f"\n[error] {type(exc).__name__}: {exc}"
        step.end_time = time.time()
        _log_error_to_console(state, f"[chapter merge {ch.id}] {type(exc).__name__}: {exc}", tb)
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
        chapter_transition = config.get("chapter_transition", "none")
        transition_duration = float(config.get("chapter_transition_duration", 1.0))
        if len(chapter_files) == 1:
            import shutil as _shutil
            step.output += f"\nCopying {Path(chapter_files[0]).name} → final.mp4"
            _shutil.copy2(chapter_files[0], str(final_out))
            step.output += "\nCopy done"
        else:
            step.output += (
                f"\nConcat {len(chapter_files)} chapters → final.mp4"
                f" (transition: {chapter_transition}, silence: {transition_duration}s)"
            )
            await _moviepy_concat(
                chapter_files, str(final_out),
                transition=chapter_transition, duration=transition_duration,
            )
            step.output += "\nConcat done"
    except Exception as exc:
        tb = traceback.format_exc()
        step.status = "error"
        step.output += f"\n[error] {type(exc).__name__}: {exc}"
        step.end_time = time.time()
        _log_error_to_console(state, f"[final merge] {type(exc).__name__}: {exc}", tb)
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


_TRANSITION_CHOICES = ("fade", "crossfade")


async def _moviepy_concat(
    clip_files: list[str], output: str, transition: str = "none", duration: float = 1.0
) -> None:
    """Concatenate video files with moviepy. Raises on failure — caller handles."""
    def _do_concat():
        import os
        import random as _random
        import numpy as np
        from moviepy import VideoFileClip, ColorClip, concatenate_videoclips
        from moviepy.video.fx import FadeIn, FadeOut, CrossFadeIn, CrossFadeOut

        resolved = transition if transition != "random" else _random.choice(_TRANSITION_CHOICES)
        clips = [VideoFileClip(f) for f in clip_files]
        n = len(clips)
        size = clips[0].size

        def _silence_clip():
            # Black video with explicit stereo silence so concatenation audio is consistent.
            # AudioArrayClip is used instead of AudioClip because moviepy renders audio in
            # chunk-sized arrays; a scalar lambda returns shape (2,) for any input which
            # produces ~0 audio samples and drops the silence from the output.
            from moviepy.audio.AudioClip import AudioArrayClip
            n_samples = max(1, round(duration * 44100))
            audio = AudioArrayClip(np.zeros((n_samples, 2), dtype=np.float32), fps=44100)
            video = ColorClip(size=size, color=(0, 0, 0), duration=duration)
            return video.with_audio(audio)

        if resolved == "crossfade" and n > 1:
            # Visual dissolve (clips overlap); CrossFadeIn/Out only work with method="compose"
            d = duration
            processed = []
            for i, c in enumerate(clips):
                fx = []
                if i > 0:
                    fx.append(CrossFadeIn(d))
                if i < n - 1:
                    fx.append(CrossFadeOut(d))
                processed.append(c.with_effects(fx) if fx else c)
            result = concatenate_videoclips(processed, method="compose", padding=-duration)

        elif resolved == "fade" and n > 1:
            # Fade to black + silence gap + fade from black
            half = duration / 2
            parts = []
            for i, c in enumerate(clips):
                if i > 0:
                    parts.append(_silence_clip())
                fx = []
                if i > 0:
                    fx.append(FadeIn(half))
                if i < n - 1:
                    fx.append(FadeOut(half))
                parts.append(c.with_effects(fx) if fx else c)
            result = concatenate_videoclips(parts)

        elif n > 1 and duration > 0:
            # "none" — silent gap between chapters, hard video cuts
            parts = []
            for i, c in enumerate(clips):
                if i > 0:
                    parts.append(_silence_clip())
                parts.append(c)
            result = concatenate_videoclips(parts)

        else:
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
        "narrative_guidance": config.get("narrative_guidance", ""),
        "image_style": config.get("image_style", "cinematic, dramatic lighting"),
    }
    for k, v in subs.items():
        template = template.replace(f"{{{k}}}", str(v))
    return template


async def _apply_story_prompt(
    step: StepState, state: "ProjectState", config: dict, key: str, content_file: Path,
    extra_subs: dict | None = None,
) -> int:
    """Apply a storyboard prompt.

    Uses the named prompt from the prompt store (config["prompts"][key]) and lets
    the prompt CLI substitute the config placeholders. If an inline override is
    configured (config["prompt_overrides"][key]), it is applied directly instead.
    `extra_subs` are additional placeholder=value pairs appended to the apply call.
    """
    prompts = config.get("prompts") or {}
    overrides = config.get("prompt_overrides") or {}
    name = prompts.get(key, "")
    override = overrides.get(key, "")

    if override and override.strip():
        # Legacy inline path: substitute config vars, escape braces, append {content}.
        template = _resolve_prompt(override, config)
        # Also substitute any extra subs present in the inline template.
        for k, v in (extra_subs or {}).items():
            template = template.replace("{" + k + "}", str(v))
        prompt_arg = template.replace("{", "{{").replace("}", "}}") + "{content}"
        return await _run(
            step, _prompt_cmd(), "apply", prompt_arg,
            "--format", "text", f"content=@{content_file}", log_to=state,
        )

    subs = {
        "lang": config.get("language", "en"),
        "chapter_range": config.get("chapter_range", "2–5"),
        "scene_range": config.get("scene_range", "2–5"),
        "scene_duration": config.get("scene_duration", "15–45 seconds"),
        "narrative_style": config.get("narrative_style", "documentary narration"),
        "narrative_guidance": config.get("narrative_guidance", ""),
        "image_style": config.get("image_style", "cinematic, dramatic lighting"),
    }
    subs.update(extra_subs or {})
    args = [_prompt_cmd(), "apply", name, "--format", "text", f"content=@{content_file}"]
    for k, v in subs.items():
        args.append(f"{k}={v}")
    return await _run(step, *args, log_to=state)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:40] or "untitled"
