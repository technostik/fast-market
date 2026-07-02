# sound-agent

## Purpose
AI sound generation CLI tool with TTS (Kokoro, Qwen3-TTS) and music generation (MusicGen). Provides a modular plugin system for multiple sound generation engines with CLI commands.

## Architecture Overview

```
sound-cli/
├── sound_entry/           # CLI entry point (NOT cli/!)
│   └── __init__.py        # Imports main from cli.main
├── core/                  # Core logic (models, config)
├── plugins/               # Engine plugins (kokoro, qwen3, musicgen)
├── commands/              # CLI commands (speak, music, prosody, charisma, normalize-volume)
└── common/                # Symlink to shared utilities
```

## Essential Components

### Core (`core/`)

| File | Purpose |
|------|---------|
| `models.py` | `TTSRequest`, `TTSResult`, `MusicGenResult`, `ProsodyResult`, `CharismaResult` dataclasses |
| `config.py` | Config loading and default values |

### Plugins (`plugins/`)

| File | Purpose |
|------|---------|
| `base.py` | `TTSPlugin` ABC, `MusicGenPlugin` ABC, `PluginManifest` |
| `kokoro/plugin.py` | `KokoroPlugin` - weighted voice mixing TTS |
| `kokoro/register.py` | Declares kokoro plugin to the system |
| `qwen3/plugin.py` | `Qwen3TTSPlugin` - dual-model voice design + cloning with stable reference caching |
| `qwen3/register.py` | Declares qwen3 plugin to the system |
| `musicgen/plugin.py` | `MusicGenModelPlugin` - text-to-music generation |
| `musicgen/register.py` | Declares musicgen plugin to the system |

### Commands (`commands/`)

| File | Purpose |
|------|---------|
| `base.py` | `CommandManifest` dataclass |
| `helpers.py` | `build_engine()` - instantiates plugins from config |
| `speak/` | `sound speak` command |
| `music/` | `sound music` command |
| `prosody/` | `sound prosody` command - `analysis.py` (signal processing/scoring) + `register.py` (CLI wiring) |
| `charisma/` | `sound charisma` command - reuses `prosody.analysis` + adds intonation/voice-quality proxies |
| `normalize_volume/` | `sound normalize-volume` command - dynamic (compressor-based) volume normalization against a cached reference level |
| `scoring.py` | Shared `target_band_score()` / `inverse_band_score()` curves used by both `prosody` and `charisma` |

## Core Responsibilities

### Text-to-Speech
- Accept text input with voice and speed parameters
- Support multiple TTS engines (kokoro with voice embeddings, qwen3 with voice design)
- Weighted voice mixing for kokoro (e.g. `am_michael*0.7,am_fenrir*0.3`)
- Natural language voice descriptions for qwen3
- **Qwen3 stable voice system**: dual-model architecture (VoiceDesign + Base) with hash-based reference caching
- Optional voice cloning via `clone` + `ref_text` config keys
- Three text sources: positional argument, `--file` path, or stdin pipe
- Save WAV output to workdir

### Music Generation
- Accept text prompts with duration control
- Generate music using MusicGen models
- Save WAV output to workdir

### Prosody Analysis
- Accept an audio or video file (video audio is extracted via `ffmpeg` subprocess)
- Score pitch/intonation, loudness dynamics, pausing/rhythm, and speaking rate via `librosa` (pyin, RMS, silence splitting, onset detection) — no ML model, fully offline
- Each dimension is scored 0-100 against a heuristic "ideal band" (see `commands/prosody/analysis.py` constants), then combined into a weighted `global_score`
- Plugin-free: this is a pure analysis command, not a swappable engine — see Extension Points below

### Charisma Analysis
- Builds on `sound prosody`: calls `score_prosody()` directly for pitch/energy/rhythm/rate, then adds intonation dynamism (rate of F0 direction reversals) and voice-quality proxies (spectral centroid resonance, harmonic-vs-percussive clarity via HPSS, F0/RMS frame-to-frame perturbation as jitter/shimmer proxies)
- Combines into `charisma_score` with 70% prosody / 20% voice quality / 10% derived "other" weighting (see `commands/charisma/analysis.py` constants)
- `percentile_estimate` and the `notes` strengths/weaknesses summary are explicitly labeled approximations, not validated against real normative or population data — do not present them as more precise than that when extending this feature
- Voice-quality proxies are **not** clinical Praat-style jitter/shimmer/HNR (that needs `parselmouth`, not installed) — if true clinical-grade measurement is ever needed, that's a deliberate new dependency decision, not a silent swap

### Volume Normalization
- `sound normalize-volume set-reference <file>` measures a reference file's mean volume (`ffmpeg -af volumedetect`, dBFS) **once** and caches it in `~/.config/fast-market/sound/config.yaml` under `normalize_volume: {reference_path, reference_mean_volume_db}` — later `apply` runs never re-analyze the reference
- `sound normalize-volume apply <video> [-o output]` measures the target video's current mean volume, then applies dynamic-range compression + makeup gain (`ffmpeg`'s `acompressor` filter, threshold=-30dB, ratio=4, attack=20ms, release=200ms) sized to close the gap to the reference, writing a new file by default (`<name>_normalized<ext>`) with the video stream copied untouched
- Ported from YouTools' `normalize_full_audio()` (`lib/video_utils.py`, used by its `directpublish` plugin) because a flat mean-based gain shift is wrong when a video mixes sections of very different loudness (e.g. voice narration + a louder commented clip) — compression reacts within the file instead of shifting everything by one flat number
- **Bug fixed while porting**: the original computed `makeup_gain` in dB but passed it directly into `acompressor`'s `makeup=` parameter, which is a **linear** multiplier (range 1-64), not dB — `commands/normalize_volume/analysis.py:compute_makeup_gain()` converts `10 ** (gain_db / 20)` before clamping. Threshold/ratio/attack/release and the overall algorithm are otherwise unchanged from the reference implementation
- `set-reference SOURCE` also accepts a YouTube URL (watch/`youtu.be`/`shorts`, detected via `common/youtube/utils.py:extract_video_id()`, shared with `youtube-cli`/`corpus-cli`) instead of a local file. Only the first `--duration` seconds (default 60s) are downloaded via `yt_dlp`'s `download_ranges` (HTTP range requests against YouTube's DASH streams — the same `yt_dlp.YoutubeDL(...)` library pattern as `common/youtube/transport.py`/`youtube-cli/commands/get_video`), not the whole video; the temp clip is deleted after measuring, and the config's `reference_path` stores the original URL (not the discarded temp path) as a label. Requires the optional `youtube` extra (`pip install 'sound-agent[youtube]'`)
- `sound normalize-volume measure <file> [-F json|text|yaml]` reports a file's current mean volume without changing anything — read-only wrapper around `measure_mean_volume()`, used by callers (e.g. `webux-cli`'s charisma UI) that want to display/cache a volume score independent of normalizing
- `apply` also re-measures the file it just wrote (`Output volume:` line) and reports it alongside `Input volume:`/`Reference:`/`Makeup gain:` — this is a self-check: the reported output dB is read back from the actual output file's audio, not just computed from the makeup gain, so a caller (or a human) can immediately see the real before/after numbers rather than trusting that the ffmpeg command did what was asked
- **Closed-loop correction pass (`residual_correction_gain`/`apply_flat_gain` in `commands/normalize_volume/analysis.py`)**: `compute_makeup_gain()` is an *open-loop* estimate from a single before/after mean-volume gap — it can't predict how much the compressor's own ratio-based attenuation (on any content above `THRESHOLD_DB`) will additionally reduce the mean. For files with a wide dynamic range (quiet overall but with loud passages), that reduction can outweigh the makeup boost entirely, landing the result further from the target than the input was (real case: -25.2dB input, -16.0dB target, single-pass output only reached -23.3dB). Fix: after the compressor pass, `apply` measures the real output and — if it's off target by more than `CORRECTION_TOLERANCE_DB` (0.5dB) — runs one more flat-gain pass (`volume=XdB` only, no further compression) to close the exact residual, printed as a `Correction:` line. This preserves the compressor's per-section dynamic shaping (verified: a mixed quiet/loud test file still ends up with its two sections ~18dB apart post-normalization, not flattened to one number) while guaranteeing the *overall* file lands within tolerance of the reference regardless of its dynamic profile.
  - The correction pass includes `alimiter=limit=0.891:level=false` as a safety ceiling (~-1dBTP, a standard margin for lossy-codec encode overshoot) — a positive correction can push already-loud peaks toward 0dBFS/clipping, and a real test case did land at `max_volume: 0.0 dB` (borderline) before this was added. **Gotcha discovered here**: `alimiter`'s `level` option defaults to `true` ("auto level"), which re-optimizes output gain back up toward full scale regardless of what `limit=` is set to — `level=false` is required for `limit` to actually act as a hard ceiling

### Plugin System
- Auto-discover plugins from `plugins/*/register.py`
- Two distinct plugin types: `TTSPlugin` and `MusicGenPlugin`
- Commands filter engines by type using `issubclass` checks
- Each plugin declares its capabilities via `PluginManifest`

### Configuration
- XDG-compliant config path: `~/.config/fast-market/sound/config.yaml`
- Common workdir from `~/.config/fast-market/common/config.yaml`
- Engine-specific settings (voice, speed, model, duration)
- Default engine and per-engine defaults

## Configuration Schema

```yaml
# ~/.config/fast-market/sound/config.yaml

default_engine: kokoro

kokoro:
  voice: am_michael*0.7,am_fenrir*0.3
  speed: 1.0
  language: en

qwen3:
  voice: "A warm, friendly male voice with a professional tone"
  language: en
  voice_design_model: Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
  base_model:          Qwen/Qwen3-TTS-12Hz-1.7B-Base
  clone: null            # path to reference .wav for voice cloning
  ref_text: null         # transcript of clone audio (ICL mode)

musicgen:
  model: facebook/musicgen-medium
  duration: 5.0

output_format: wav
```

### Per-Language Overrides

Engine sections can include a `languages` map. When `--language` / `-L` matches a key, its values merge on top of the parent config — useful for assigning different voices per language.

```yaml
kokoro:
  voice: am_michael*0.7,am_fenrir*0.3
  speed: 1.0
  language: en
  languages:
    fr:
      voice: ff_siwis
    ja:
      voice: jf_alpha,jf_gongitsune*0.5
      speed: 1.2

qwen3:
  voice: "A warm, friendly male voice"
  language: en
  languages:
    fr:
      voice: "Une voix féminine douce"
    zh:
      voice: "A warm female Chinese voice"
```

## Stable Voice System (Qwen3)

The Qwen3 plugin uses two HuggingFace models:

| Model | Config key | Purpose |
|-------|-----------|---------|
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | `voice_design_model` | Creates reference audio from NL description via `generate_voice_design()` |
| `Qwen3-TTS-12Hz-1.7B-Base` | `base_model` | Clones reference via `generate_voice_clone()` for stable TTS |

### Voice identity

A SHA‑256 hash (first 16 hex chars) is computed from a composite key:

| Scenario | Key |
|----------|-----|
| No clone | `voice` (the description string) |
| With clone | `voice||clone_path||ref_text` |

If the cached reference exists at `~/.cache/fast-market/sound/ref_voices/{hash}.wav` it is reused; otherwise a new one is generated.

### Reference creation

| Config | Model used | Method |
|--------|-----------|--------|
| No clone | VoiceDesign | `generate_voice_design(instruct=voice, do_sample=False)` |
| Clone (+ ref_text) | Base | `generate_voice_clone(ref_audio=clone, ref_text=ref_text)` → ICL mode |
| Clone (no ref_text) | Base | `generate_voice_clone(ref_audio=clone, x_vector_only_mode=True)` |

### Synthesis (always)

```python
base_model.generate_voice_clone(text=user_text, ref_audio=ref_path, ref_text=REFERENCE_TEXT)
```

## Commands

| Command | Description |
|---------|-------------|
| `sound speak "hello"` | Synthesize speech with default engine |
| `sound speak -f script.txt` | Read text from file |
| `echo "hi" \| sound speak` | Pipe text via stdin |
| `sound speak "hello" -e qwen3 -L French` | TTS with language |
| `sound speak "hi" --voice "am_michael" --speed 1.5` | Kokoro with options |
| `sound music "lofi beat"` | Generate music from prompt |
| `sound music "jazz" -d 10` | Music with custom duration |
| `sound prosody speech.wav` | Prosody analysis with global 0-100 score |
| `sound prosody talk.mp4 --format json` | Prosody analysis of a video's audio track |
| `sound charisma speech.wav` | Charisma analysis with global 0-100 score |
| `sound charisma talk.mp4 --format json` | Charisma analysis of a video's audio track |
| `sound normalize-volume set-reference good_take.mp4` | Analyze and cache the reference volume level once |
| `sound normalize-volume set-reference https://youtu.be/VIDEO_ID` | Same, but download only the first 60s of a YouTube video (`-d` to change) |
| `sound normalize-volume apply quiet.mp4` | Dynamically normalize a video's volume against the cached reference → `quiet_normalized.mp4` |
| `sound normalize-volume apply quiet.mp4 -o out.mp4` | Normalize to an explicit output path |
| `sound --show-completion` | Print shell completion script |
| `sound --install-completion` | Install shell completion |

## Engine Interfaces

### TTSPlugin

```python
class TTSPlugin(ABC):
    name: str
    @abstractmethod
    def synthesize(self, text: str, voice: str, speed: float, **kwargs) -> tuple[torch.Tensor, int]:
        """Returns (audio_tensor, sample_rate)."""
```

### MusicGenPlugin

```python
class MusicGenPlugin(ABC):
    name: str
    @abstractmethod
    def generate(self, prompt: str, duration: float, **kwargs) -> tuple[torch.Tensor, int]:
        """Returns (audio_tensor, sample_rate)."""
```

## Voice Mixing (Kokoro)

The `_parse_voice_string()` utility parses voice strings into weighted embeddings:

```
"am_michael*0.7,am_fenrir*0.3"
  → names=["am_michael", "am_fenrir"], weights=[0.7, 0.3]
  → weighted_embedding = voice_embedding(am_michael) * 0.7
                        + voice_embedding(am_fenrir) * 0.3
```

If weights are omitted, they are normalized equally. If only some have weights, unweighted voices split the remaining weight evenly.

## Dependencies & Integration

### External Dependencies
- `torch` - tensor operations and model inference
- `click` - CLI framework
- `pyyaml` - config loading
- `soundfile` - audio file I/O
- `librosa` - prosody/charisma analysis (pitch, energy, rhythm, voice quality)
- `ffmpeg` (system binary) - audio extraction from video for `prosody`/`charisma`; `volumedetect`/`acompressor` audio filters for `normalize-volume`
- `kokoro` - Kokoro TTS engine (optional)
- `qwen-tts` - Qwen3-TTS engine (optional)
- `transformers` - MusicGen model (core dep)
- `yt-dlp` - downloads a partial (first N seconds) YouTube clip for `normalize-volume set-reference <url>` (optional, `youtube` extra)

### Integrations
- Imports from `common/` (cli, core, registry)
- Plugin system follows the fast-market agent pattern
- Config uses XDG paths from common
- Output goes to common workdir

## Do's

- Use `build_engine()` from helpers to construct plugins
- Use `load_sound_config()` for config with defaults
- Use `out()` for consistent output formatting
- Use `**kwargs` to absorb future engine options
- Filter engine choices by `issubclass` checks (TTS vs music)

## Don'ts

- Hardcode plugin names - use manifests
- Hardcode paths - use XDG from common
- Call TTS methods on music engines or vice versa
- Swallow exceptions - FAIL LOUDLY
- Use global state for engine instances

## Extension Points

### Add New TTS Engine

1. Create `plugins/your_engine/plugin.py` implementing `TTSPlugin`
2. Create `plugins/your_engine/register.py` returning `PluginManifest`
3. Add engine config defaults to `core/config.py`
4. Engine auto-appears in `speak` command choices

### Add New Music Engine

1. Create `plugins/your_engine/plugin.py` implementing `MusicGenPlugin`
2. Create `plugins/your_engine/register.py` returning `PluginManifest`
3. Add engine config defaults to `core/config.py`
4. Engine auto-appears in `music` command choices

### Add New CLI Command

1. Create `commands/your_command/` with `__init__.py` and `register.py`
2. Implement `register(plugin_manifests) -> CommandManifest`
3. Registry auto-discovers and registers

Not every command needs the plugin/engine system — `prosody` is a plain analysis
command with no swappable engines, so its `register()` simply ignores
`plugin_manifests` (matches the `music`/`speak` signature for consistency, but
ignores unused arg instead of wiring an engine).

## Related Documentation

- See `_doc/BUILD_NEW_AGENT_CLI.md` for the agent architecture pattern
- See `.doc/GOLDEN_RULES.md` for architectural principles
- See `common/core/registry.py` for plugin discovery
