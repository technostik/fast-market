# voiceboard — WebUX Plugin

Build a narrated, illustrated video from an **existing voice file** (.ogg, .mp3,
.mp4, .wav). The voice is transcribed and cut into timed scenes, then each scene
gets an AI-generated illustrative image (same Ken Burns animation options as
storyboard) and is assembled into a final video.

## Architecture

```
webux-cli/webux/voiceboard/
├── register.py   FastAPI router + HTML frontend (WebuxPluginManifest)
├── config.py     load/save voiceboard config (image + segmentation params)
├── pipeline.py   Async pipeline orchestration (reuses storyboard step functions)
├── models.py     Re-exports storyboard models (ProjectState, Scene, …)
└── AGENTS.md
```

The pipeline **reuses storyboard's per-scene step functions** (`_gen_image_prompt`,
`_gen_image`, `_assemble_clip`, chapter/final merge) by importing them from
`webux.storyboard.pipeline`. The only difference is the *ingestion* stage: instead
of an LLM breaking a markdown script into chapters/scenes (`_parse_script`),
voiceboard runs **`sound segment`** to transcribe the voice and cut it into
timed scenes. The transcript and audio are then treated as the already-done
`gen_transcript` / `gen_audio` steps, so the pipeline skips TTS entirely.

## Pipeline stages

| Global step | What happens |
|---|---|
| `segment` (parse) | `sound segment <voice>` → `segments.json` + per-segment WAVs; scenes built with `transcript` + `audio_file` pre-set, `gen_transcript`/`gen_audio` marked **done** |
| `image_prompt` | `prompt apply scene_image_prompt` → image prompt from the scene's narration text (LLM) |
| `image` | `image generate <prompt>` → one still image per scene |
| `clip` | `video assemble <image> <segment_audio>` → Ken Burns clip whose length == the segment's audio |
| `chapter` / `final` | moviepy concatenation (optional transition + silence gap) |

## Configuration (relevant keys)

Config holds only what does **not** change between sessions. The voice source
(`voice_file` / `segments_json`) is deliberately **not** in config — it is
per-project/session, stored on the `VoiceboardState` in `state.json` (see below).

Voice ingestion (cross-session defaults):
- `transcript_engine` — `whisperx` (local word-aligned; uses whisperx if installed else faster-whisper) or `groq` (hosted whisper-large-v3, needs `GROQ_API_KEY`).
- `transcript_model` — model size (e.g. `medium`).
- `language` — language code or `en`.
- `segment_min` / `segment_max` / `segment_silence` — segmentation targets. Default 10s / 30s / 0.6s. Raise `segment_max` (e.g. 180) to keep one image for a long stretch during tests.

Image / animation (mirrors storyboard): `image_engine`, `image_size`,
`image_style`, `narrative_style`, `ken_burns_zoom_from/to`, `ken_burns_motion`,
`fps`, `draft_mode`, `chapter_transition`, `chapter_transition_duration`, `prompts`.

### Voice source flow (UI + upload)

The voice source is chosen in the UI via a **native file picker** and uploaded to
the workdir, not typed as a config path.

- `POST /api/voiceboard/upload?kind=voice|segments` (multipart `file`) copies the
  picked file into `{workdir}/voiceboard/sources/` and returns its absolute path.
- That path is passed to `POST /init` (`voice_file` or `segments_json`) and stored
  on `VoiceboardState` in `state.json`. It is **not** written to global config.
- `_ingest_voice` reads the source from `state.voice_file` / `state.segments_json`,
  not from config.

`VoiceboardState` (in `voiceboard/models.py`) is a `ProjectState` subclass adding
`voice_file` and `segments_json` (both `""` by default, persisted with state.json).

## `sound segment` (the cutting command)

```
sound segment VOICE_FILE
  [--output-dir DIR] [--engine whisperx|groq] [--model medium]
  [--language auto] [--min-segment 10] [--max-segment 30] [--silence 0.6]
  [--format json|text]
```

Segmentation is **deterministic and audio-driven** (Option A):
1. Transcribe with word-level timestamps (whisperx/faster-whisper or Groq).
2. Initial units = sentence-level segments.
3. Over-long units (> `max-segment`) are split at the largest internal silence.
4. Short units (< `min-segment`) are merged with the next, unless that would
   blow past `max-segment`.
5. Any remaining over-long units are split again.

Outputs `<output-dir>/segments.json` (list of `{index,start,end,text,audio}`),
`<output-dir>/segments/seg_NNN.wav` (one per scene), and `script.txt`.

## API endpoints (under `/api/voiceboard/`)

`GET /config`, `POST /config`, `GET /state`, `POST /init` (voice file or
segments.json + segmentation params), `POST /upload` (multipart voice/segments),
`POST /run`, `POST /stop`, `GET /job`,
`POST /scene/{id}`, `GET /preview`, `GET /download`.

## Adding the tab

Registered in `webux-cli/pyproject.toml` under `fast_market.webux_plugins`
(`voiceboard = "webux.voiceboard.register:register"`). After changing
`pyproject.toml`, reinstall: `pip install -e .` and restart `webux serve`.
