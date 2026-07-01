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
├── commands/              # CLI commands (speak, music, prosody, charisma)
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
- `ffmpeg` (system binary) - audio extraction from video for `prosody`/`charisma`
- `kokoro` - Kokoro TTS engine (optional)
- `qwen-tts` - Qwen3-TTS engine (optional)
- `transformers` - MusicGen model (core dep)

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
