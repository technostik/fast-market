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
  parse_step: StepState
  chapters[]:
    Chapter
      scenes[]:
        Scene (id="ch00_sc01")
          steps: {gen_transcript, gen_image_prompt, gen_audio, gen_image, assemble_clip}
          audio_file, image_file, clip_file
      merge_step: StepState
      chapter_file
  final_step: StepState
  final_file
```

## Pipeline stages

| Global step | Scene-level key | Tool invoked |
|---|---|---|
| parse | — | `prompt apply --stdin` (JSON response parsed) |
| transcript | gen_transcript | `prompt apply --stdin` |
| image_prompt | gen_image_prompt | `prompt apply --stdin` |
| audio | gen_audio | `sound speak --file` |
| image | gen_image | `image generate` |
| clip | assemble_clip | `video assemble` |
| chapter | merge_step | moviepy `concatenate_videoclips` |
| final | final_step | moviepy `concatenate_videoclips` |

## File layout in workdir

```
{workdir}/storyboard/
├── state.json
├── chapters/
│   └── ch00_<title>/
│       ├── chapter.mp4
│       └── scenes/
│           └── ch00_sc00_<title>/
│               ├── description.txt
│               ├── transcript.txt
│               ├── image_prompt.txt
│               ├── audio.wav
│               ├── image.png (or .jpg/.webp)
│               └── clip.mp4
└── final.mp4
```

## Re-run semantics

- **Full run**: `POST /run {}` — runs from parse if parse is not done, otherwise continues from first pending step.
- **Global re-run**: `POST /run {from_global_step: "audio"}` — clears and re-runs that stage and all downstream for every scene.
- **Scene re-run**: `POST /run {scene_id: "ch00_sc01", from_step: "gen_image"}` — clears from_step and downstream for that scene only, then re-runs chapter + final merges.

## Config

Stored at `~/.config/fast-market/profiles/<profile>/storyboard.yaml`. Key fields:

```yaml
tts_engine: kokoro         # kokoro | qwen3
image_engine: flux2cloud   # flux2cloud | flux2
image_size: landscape
image_style: "cinematic, dramatic lighting, photorealistic"
narrative_style: "documentary, dramatic third-person narration"
ken_burns_zoom_from: 1.0
ken_burns_zoom_to: 1.3
fps: 24
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
- `POST /api/storyboard/init` — `{script_path}` → create state.json
- `POST /api/storyboard/run` — `{from_global_step?, scene_id?, from_step?}` → start pipeline
- `GET  /api/storyboard/job` — poll: full state + `running` flag (1.5s polling from UI)
- `POST /api/storyboard/stop` — cancel current asyncio task
- `POST /api/storyboard/scene/{id}` — `{transcript?, image_prompt?}` → save edits
- `GET  /api/storyboard/preview?file=` — serve media with correct MIME
- `GET  /api/storyboard/download?file=` — download any output file

## ⚠️ Pitfalls

- **parse_script JSON parsing**: The LLM response may include markdown fences around the JSON. `_parse_script` strips them with a regex before `json.loads`. If the LLM returns non-JSON text, the step will fail with a clear error.
- **image path detection**: `image generate --format json` outputs a JSON line with `path`. `_extract_json_path` parses it. If it fails, we fall back to glob for the newest PNG/JPG in the scene dir.
- **chapter/final merge**: Uses `asyncio.to_thread` so moviepy does not block the event loop. A single-scene chapter copies the file instead of invoking moviepy.
- **workdir requirement**: If `workdir` is not set in common config, all endpoints return 400. Run `toolsetup` to configure it.
- **Ken Burns temp audio**: moviepy writes a temp audio file during assembly. It is placed next to the output file (not in `/tmp`) to avoid CWD issues, matching the pattern in `remove_silence`.
