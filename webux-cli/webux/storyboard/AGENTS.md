# storyboard — WebUX Plugin

Fully automated video generation pipeline driven from a single plain-text script file.

## Architecture

```
webux-cli/webux/storyboard/
├── register.py   FastAPI router + HTML frontend (WebuxPluginManifest)
├── models.py     Dataclasses: ProjectState, Chapter, Scene, StepState
├── pipeline.py   Async pipeline orchestration (subprocess-based)
├── config.py     load/save storyboard config, default prompts
└── __init__.py
```

The pipeline also uses `video assemble` (video-cli/commands/assemble/) for Ken Burns clip assembly.

## State model

All pipeline state lives in `{workdir}/storyboard/state.json`. The file is written after every sub-step so the UI always reflects the latest state. In-memory state is kept in `pipeline._current_state` while a task is running.

```
ProjectState
  script_text: str
  parse_step: StepState
  character_step: StepState        # optional pre-pipeline step
  character_description: str        # reused in every scene image prompt ({character})
  character_image: str | None      # 3/4 reference PNG in workdir
  chapters[]:
    Chapter
      scenes[]:
        Scene (id="ch00_sc01")
          steps: {gen_transcript, gen_image_prompt, gen_audio, gen_image, assemble_clip}
          transcript, image_prompt
          audio_file, audio_duration (seconds)
          image_file, clip_file
      merge_step: StepState
      chapter_file
  final_step: StepState
  final_file
  console_log: [{t, cmd, output, rc}]  # rolling 200-entry log

StepState fields:
  status: pending|running|done|error|skipped
  output: str
  start_time, end_time: float | None
  elapsed_seconds: float | None    (computed in to_dict)
  output_file: str | None          (path to the produced file)
```

## Pipeline stages

| Global step | Scene-level key | Tool invoked |
|---|---|---|
| character | — (optional, pre-pipeline) | `prompt apply storyboard-character content=@script.txt` → description, then `image generate` (3/4 portrait) → `character.png`. Skipped unless `character_enabled` in config. |
| parse | — | `prompt apply <template> --format text content=@script.txt` |
| transcript | gen_transcript | `prompt apply <template> --format text content=@description.txt` |
| image_prompt | gen_image_prompt | `prompt apply <template> --format text content=@image_prompt_input.txt` |
| audio | gen_audio | `sound speak --file transcript.txt --engine <tts_engine> --language <lang> --output audio.wav` |
| image | gen_image | `image generate <prompt> --engine <image_engine> --output-dir <scene_dir> --format json [--size / --width/height] [--steps] [--seed]` |
| clip | assemble_clip | `video assemble <image> <audio> --output clip.mp4 --motion <ken_burns_motion> --fps <fps>` |
| chapter | merge_step | moviepy `concatenate_videoclips` (or copy if single scene) — no transition, hard cut |
| final | final_step | moviepy `_moviepy_concat` with configurable transition + silence gap between chapters |

Prompt templates support placeholders: `{lang}`, `{chapter_range}`, `{scene_range}`, `{scene_duration}`, `{narrative_style}`, `{image_style}`. These are resolved by `_resolve_prompt()` before the prompt CLI escaping step.

## File layout in workdir

```
{workdir}/storyboard/
├── state.json
├── script.txt                   (copy of the pasted script, written at parse time)
├── chapters/
│   └── ch00/                    (id only — no title in path)
│       ├── chapter.mp4
│       └── scenes/
│           └── ch00_sc00/       (id only)
│               ├── description.txt
│               ├── transcript.txt
│               ├── image_prompt_input.txt
│               ├── image_prompt.txt
│               ├── audio.wav
│               ├── image.png (or .jpg/.webp)
│               └── clip.mp4
└── final.mp4
```

## Re-run semantics

- **Full run / run remaining**: `POST /run {}` — runs from parse if parse is not done, otherwise continues from first pending step.
- **Global re-run from step**: `POST /run {from_global_step: "audio"}` — clears and re-runs that stage and all downstream for every scene.
- **Run only one global step**: `POST /run {only_global_step: "image"}` — runs that single stage for all scenes; no cascade.
- **Scene re-run (cascade)**: `POST /run {scene_id: "ch00_sc01", from_step: "gen_image"}` — clears from_step and downstream for that scene only, then re-runs chapter + final merges.
- **Scene re-run (no cascade)**: `POST /run {scene_id: "ch00_sc01", from_step: "gen_image", only_scene: true}` — stays within the scene, no chapter/final cascade.
- **Single step re-run**: `POST /run {scene_id: "ch00_sc01", from_step: "gen_audio", only_step: true}` — runs exactly that one step and stops.

## Config

Stored at `~/.config/fast-market/profiles/<profile>/storyboard.yaml`. Key fields:

```yaml
tts_engine: kokoro           # kokoro | qwen3
language: en                 # narration language passed to sound speak
image_engine: flux2cloud     # flux2cloud | flux2
image_size: landscape        # landscape | square | portrait | youtube | wide
image_style: "cinematic, dramatic lighting, photorealistic"
narrative_style: "documentary, dramatic third-person narration"
narrative_guidance: ""        # broader story context injected into every scene transcript ({narrative_guidance})
animation_style: ken_burns   # currently only ken_burns is used
ken_burns_zoom_from: 1.0
ken_burns_zoom_to: 1.3
ken_burns_motion: random     # random | zoom_in | zoom_out | pan_right | pan_left | … (see UI for all options)
fps: 24
image_seed: null             # null = random each time
image_steps: null            # null = engine default
draft_mode: false            # true → 512×288 images at draft_steps (fastest preview)
draft_steps: 1
chapter_transition: none     # none | fade | crossfade | random — applied between chapters in final merge
chapter_transition_duration: 1.0   # seconds — controls both the silence gap and the visual effect duration
chapter_range: "2–5"         # injected as {chapter_range} into story_breakdown prompt
scene_range: "2–5"           # injected as {scene_range}
scene_duration: "15–45 seconds"   # injected as {scene_duration}
prompts:
  story_breakdown: "..."
  scene_transcript: "..."
  scene_image_prompt: "..."
```

All prompts are editable live in the WebUX Config panel.

## API endpoints

- `GET  /api/storyboard/config` — get plugin config
- `POST /api/storyboard/config` — save plugin config
- `GET  /api/storyboard/state` — load state.json (or `{"initialized": false}`)
- `POST /api/storyboard/init` — `{script_text}` → create state.json, workdir taken from common config
- `POST /api/storyboard/script` — `{script_text}` → update script on existing project, reset parse_step and chapters
- `POST /api/storyboard/run` — `{from_global_step?, only_global_step?, scene_id?, from_step?, only_step?, only_scene?}` → start pipeline
- `GET  /api/storyboard/job` — poll: full state + `running` flag + `global_steps` summary (1.5s polling from UI)
- `POST /api/storyboard/stop` — cancel current asyncio task
- `POST /api/storyboard/scene/{id}` — `{transcript?, image_prompt?}` → save edits and persist to disk
- `GET  /api/storyboard/preview?file=` — serve media with correct MIME
- `GET  /api/storyboard/download?file=` — download any output file

## ⚠️ Polling vs. media playback — mandatory pattern

The UI polls `GET /api/storyboard/job` every 1.5 s. Any panel that calls `innerHTML = ...` on every poll will destroy `<audio>` and `<video>` elements mid-playback.

**Never** write an unconditional render in `applyState`. Always use the three-part guard:

```js
// 1. Compute a JSON fingerprint of the data slice this view cares about
const j = JSON.stringify(data.chapters || []);
// 2. Mark pending when the data actually changed
if (j !== _lastXJson) _pendingXUpdate = true;
// 3. Flush only when the panel is free (no media playing, no textarea focused)
if (_pendingXUpdate && !_xIsBusy()) {
  _lastXJson = j; _pendingXUpdate = false;
  renderX(data.chapters || []);
}
```

The `_xIsBusy()` helper must check both focused inputs and playing media:

```js
function _xIsBusy() {
  const el = document.getElementById('xPanel');
  if (!el) return false;
  const a = document.activeElement;
  if (a && el.contains(a) && (a.tagName === 'TEXTAREA' || a.tagName === 'INPUT')) return true;
  return [...el.querySelectorAll('audio,video')].some(m => !m.paused);
}
```

State variables needed per view: `_lastXJson = null`, `_pendingXUpdate = false`.

The detail panel (`_detailIsBusy`, `_pendingDetailUpdate`, `_lastRenderedSceneJson`), format view (`_formatIsBusy`, `_pendingFormatUpdate`, `_lastFormatJson`), and matrix view (`_matrixIsBusy`, `_pendingMatrixUpdate`, `_lastMatrixJson`) all follow this pattern. Any new panel that renders media must do the same.

## ⚠️ Pitfalls

- **parse_script prompt**: Uses `prompt apply <template> content=@<file>` (named file param, not `--stdin`). Config placeholders (`{lang}`, etc.) are substituted by `_resolve_prompt()` before the template is escaped. Then remaining `{` `}` are doubled to neutralize them for the prompt CLI, and `{content}` is appended as the named placeholder for the script file.
- **image path detection**: `image generate --format json` outputs a JSON line with `path`. `_extract_json_path` parses it. If it fails, falls back to glob for the newest PNG/JPG in the scene dir.
- **chapter/final merge**: Chapter merges use a plain hard-cut `concatenate_videoclips`. Only the final merge (`_assemble_final`) applies the configured `chapter_transition`. Both use `asyncio.to_thread` so moviepy does not block the event loop. A single-scene chapter (or single-chapter final) copies the file directly.
- **chapter transitions**: `none` inserts a `d`-second black+silent `ColorClip` between chapters (hard video cut). `fade` inserts the same silence clip and applies `FadeOut(d/2)` / `FadeIn(d/2)` at each chapter boundary. `crossfade` overlaps chapters by `d` seconds using `CrossFadeIn`/`CrossFadeOut` with `method="compose"` and `padding=-d` (no silence clip). `random` picks `fade` or `crossfade` at render time. `AudioClip` silence uses `frame_function=lambda t: np.zeros(2)` (stereo scalar); do **not** use the old moviepy v1 `make_frame` kwarg.
- **workdir requirement**: If `workdir` is not set in common config, all endpoints return 400. Run `toolsetup` to configure it.
- **Ken Burns temp audio**: moviepy writes a temp audio file (`temp-audio-concat.m4a`) next to the output file (not in `/tmp`) to avoid CWD issues.
- **Console log cap**: `console_log` keeps at most 200 entries; the UI trims entries from the display start via `_consoleClear` (Clear button). Pipeline errors (from `_run_safely`, `_assemble_chapter`, `_assemble_final`) are always appended to `console_log` via `_log_error_to_console()` with full traceback, regardless of which step they occur in.
- **draft_mode dimensions**: When `draft_mode=true`, image generate receives `--width 512 --height 288` and `--steps <draft_steps>` instead of `--size`. The `--size` flag is skipped entirely.
