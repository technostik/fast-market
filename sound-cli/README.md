# sound-agent

AI sound generation CLI tool with TTS (Kokoro, Qwen3-TTS) and music generation (MusicGen) support. Generate speech and music from text prompts using multiple engine plugins.

## Installation

```bash
# Install from source
cd sound-agent
pip install -e .

# Install with all engines
pip install -e ".[kokoro,qwen3,musicgen,dev]"

# Install with only specific engines
pip install -e ".[kokoro]"       # just kokoro TTS
pip install -e ".[musicgen]"     # just music generation
```

### Prerequisites

- Python 3.11 or higher
- CUDA-compatible GPU recommended for Qwen3-TTS and MusicGen
- Kokoro works well on CPU

## Configuration

Configuration is stored in XDG-compliant paths under the `fast-market` namespace:

- **Common config**: `~/.config/fast-market/common/config.yaml` (workdir shared across all tools)
- **Tool config**: `~/.config/fast-market/sound/config.yaml`
- **Cache directory**: `~/.cache/fast-market/sound/`

### Configuration File

```yaml
# ~/.config/fast-market/sound/config.yaml

default_engine: kokoro

kokoro:
  voice: am_michael*0.7,am_fenrir*0.3   # weighted voice mix
  speed: 1.0
  language: en                          # ISO 639-1: en, en-gb, es, fr, hi, it, pt, ja, zh

qwen3:
  voice: "A warm, friendly male voice with a professional tone"
  language: en                          # ISO 639-1: en, zh, ja, ko, de, fr, ru, pt, es, it
  voice_design_model: Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign   # creates reference
  base_model:          Qwen/Qwen3-TTS-12Hz-1.7B-Base          # stable TTS
  clone: null            # path to reference audio for voice cloning
  ref_text: null         # transcript of clone audio (ICL mode)

musicgen:
  model: facebook/musicgen-medium
  duration: 5.0

output_format: wav
```

Output files are written to the common config `workdir` (set in `~/.config/fast-market/common/config.yaml`).

### Stable Voice System (Qwen3)

Qwen3 uses a **dual-model architecture** for stable, reproducible voices:

1. **VoiceDesign model** (`voice_design_model`) — generates a reference audio from a natural-language voice description
2. **Base model** (`base_model`) — clones that reference for every TTS request, guaranteeing the same timbre

The voice identity is **hashed** from the voice description (+ optional `clone` config). A cached reference is stored at `~/.cache/fast-market/sound/ref_voices/{hash}.wav`. As long as none of `voice`, `clone`, or `ref_text` change, the same reference is reused.

When you change the voice description, a new hash is computed and a new reference is generated automatically.

#### Voice Cloning

Set `clone` to a `.wav` file path and optionally `ref_text` to its transcript:

```yaml
qwen3:
  voice: "A warm, friendly male voice"
  clone: /path/to/recording.wav
  ref_text: "Transcript of the recording"
```

The workflow:
1. **Base model** clones the voice from the reference audio
2. If `ref_text` is provided, ICL (In-Context Learning) mode is used for better quality; otherwise x‑vector only
3. The result is cached and reused for stable TTS

**Log messages** on stderr indicate whether a new reference is being generated or a cached one is used.

### Per-Language Overrides

You can define engine-specific settings for individual languages under a `languages` key. When `--language` matches a key, its values override the top-level engine config. Fields not specified fall back to the parent block.

```yaml
kokoro:
  voice: am_michael*0.7,am_fenrir*0.3     # fallback for unspecified languages
  speed: 1.0
  language: en
  languages:
    fr:
      voice: ff_siwis
    ja:
      voice: jf_alpha,jf_gongitsune*0.5
      speed: 1.2
    zh:
      voice: zf_xiaobei

qwen3:
  voice: "A warm, friendly male voice"
  language: en
  languages:
    fr:
      voice: "Une voix féminine douce et élégante"
      language: fr
    zh:
      voice: "A warm female Chinese voice"
```

Usage:
```bash
# picks am_michael*0.7,am_fenrir*0.3 (top-level)
sound speak "Hello"

# picks ff_siwis from languages.fr
sound speak "Bonjour" -L fr

# picks jf_alpha,jf_gongitsune*0.5 with speed 1.2 from languages.ja
sound speak "こんにちは" -L ja
```

## Commands

| Command | Description |
|---------|-------------|
| `sound speak "text"` | Synthesize speech from text |
| `sound speak "text" -e qwen3 -v "description"` | TTS with voice design |
| `sound speak "text" -e kokoro -v "am_michael" --speed 1.5` | Kokoro with options |
| `sound music "lofi piano track"` | Generate music from prompt |
| `sound music "upbeat electronic" -d 10` | Music with custom duration |
| `sound prosody speech.wav` | Analyze prosody, print a global 0-100 score |
| `sound prosody clip.mp4 --format json` | Prosody analysis of a video's audio track |
| `sound charisma speech.wav` | Estimate vocal charisma, print a global 0-100 score |
| `sound charisma clip.mp4 --format json` | Charisma analysis of a video's audio track |

### `sound speak [TEXT]`

Synthesize speech from text using a TTS engine. Text can come from three sources:

1. **Positional argument** — `sound speak "Hello world"`
2. **File** — `sound speak -f script.txt`
3. **Stdin pipe** — `echo "Hello world" | sound speak`

| Option | Short | Description |
|--------|-------|-------------|
| `--file` | `-f` | Read text from a file |
| `--engine` | `-e` | TTS engine: `kokoro` or `qwen3` (from config) |
| `--voice` | `-v` | Voice spec (semantics depend on engine) |
| `--speed` | `-s` | Playback speed, default 1.0 (kokoro only) |
| `--output` | `-o` | Output path (default: workdir/speak\_\<timestamp\>.wav) |
| `--language` | `-L` | Language (ISO 639-1 shorthand like `en`, `fr`, `es`, `ja`, `zh`) |
| `--accelerate` | `-a` | Post-processing time-stretch factor (0.25–4.0, e.g. 1.5 = 50% faster). Pitch-preserved phase vocoder, works with any engine. |
| `--format` | `-F` | Output format: `json` or `text` |

**Voice semantics by engine:**
- **kokoro**: Weighted voice mix. Format: `name[*weight,...]`. Example: `am_michael*0.7,am_fenrir*0.3`. Weights are normalized to sum to 1.0. A single name like `am_michael` uses that voice directly. Use `--language` for multilingual TTS: `en`, `en-gb`, `es`, `fr`, `hi`, `it`, `pt`, `ja`, `zh`.
- **qwen3**: Natural language voice description. Example: `"A soft, elegant French female voice"`. Use `--language` for multilingual generation: `en`, `zh`, `ja`, `ko`, `de`, `fr`, `ru`, `pt`, `es`, `it`.

**Examples:**
```bash
# Positional argument
sound speak "Hello world"

# Read from file
sound speak -f long_text.txt

# Pipe input
cat article.txt | sound speak --voice "A calm narrator voice"
fortune | sound speak -e qwen3 -L French
```

### `sound music <PROMPT>`

Generate music from a text prompt.

| Option | Short | Description |
|--------|-------|-------------|
| `--engine` | `-e` | Music engine: `musicgen` |
| `--duration` | `-d` | Duration in seconds, default 5.0 |
| `--output` | `-o` | Output path (default: workdir/music\_\<timestamp\>.wav) |
| `--format` | `-F` | Output format: `json` or `text` |

### `sound prosody <FILE>`

Analyze the prosody of a speech audio or video file — pitch/intonation, loudness dynamics, pausing/rhythm, and speaking rate — and report a global 0-100 score plus a per-dimension breakdown. Runs fully offline via `librosa` signal analysis (pitch tracking, RMS energy, silence splitting, onset detection); video files have their audio track extracted with `ffmpeg` automatically.

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Also write the full JSON report to this path |
| `--format` | `-F` | Output format: `json`, `text`, or `yaml` |

**Score breakdown:**

| Field | Meaning |
|-------|---------|
| `global_score` | Weighted overall prosody score (0-100) |
| `pitch_score` | Intonation variety, from F0 semitone range (too flat = monotone, too wide = erratic) |
| `energy_score` | Loudness dynamics, from RMS coefficient of variation |
| `rhythm_score` | Pausing pattern, from ratio of silence to total duration |
| `rate_score` | Speaking pace, from an onset-rate proxy for syllable rate |

**Examples:**
```bash
sound prosody interview.wav
sound prosody talk.mp4 --format json -o report.json
```

### `sound charisma <FILE>`

Estimate the vocal charisma of a speech audio or video file: a 0-100 score combining prosody & acoustic dynamism (70%), voice quality (20%), and expressiveness/engagement (10%), per the weighting used in vocal-charisma research (Niebuhr, Signorello, Rodero et al.). Reuses the same `sound prosody` signal analysis for pitch/energy/rhythm/rate, and adds intonation dynamism (rate of pitch direction reversals) and voice-quality proxies (spectral resonance, harmonic-vs-percussive clarity, F0/RMS perturbation as jitter/shimmer proxies). Fully offline, no new dependency beyond `librosa`.

**Important limitation:** the voice-quality subscores (`hnr_score`, `stability_score`) are *proxies* computed from frame-level signal analysis, not clinical Praat-style pitch-period jitter/shimmer/HNR measurements (that would require the `parselmouth` library, not installed here). `percentile_estimate` is a rough illustrative figure assuming charisma scores are normally distributed (mean 50, sd 15) across speakers in general — it is **not** derived from a validated normative dataset or research on media professionals, so treat it as a rough compass, not a citation.

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Also write the full JSON report to this path |
| `--format` | `-F` | Output format: `json`, `text`, or `yaml` |

**Score breakdown:**

| Field | Meaning |
|-------|---------|
| `charisma_score` | Weighted overall score: 70% prosody, 20% voice quality, 10% other |
| `prosody_features_score` | Mean of pitch, energy, rhythm, rate, and intonation subscores |
| `voice_quality_score` | Mean of resonance, harmonic-clarity, and stability subscores |
| `other_score` | Derived expressiveness/engagement composite (intonation + energy + rate) |
| `intonation_score` | Dynamism of pitch contour — rate of rise/fall direction changes |
| `resonance_score` | Spectral centroid as a rough timbre/resonance proxy |
| `hnr_score` | Harmonic-vs-percussive energy ratio as a rough clarity proxy |
| `stability_score` | Mean of jitter and shimmer proxies (frame-level F0/RMS perturbation) |
| `percentile_estimate` | Illustrative percentile only — see limitation note above |
| `notes` | Rule-based strengths/weaknesses derived from the subscores above |

The JSON output also includes the **raw metrics** behind each subscore, useful for direct comparison between recordings rather than just the normalized 0-100 scores: `median_f0_hz`, `semitone_range`, `rms_cv`, `pause_count_per_min`, `estimated_rate_per_sec`, `reversals_per_sec`, `spectral_centroid_hz`, `hnr_proxy_db`, `jitter_proxy`, `shimmer_proxy`.

**Examples:**
```bash
sound charisma interview.wav
sound charisma keynote.mp4 --format json -o report.json
```

## Engines

### Kokoro (TTS)
- **Package**: `kokoro>=0.9`
- **Model**: `hexgrad/Kokoro-82M` (auto-downloaded on first use)
- **Voices**: Weighted mixing across 9 languages (voice prefix = lang code: `am_*`, `bf_*`, `ef_*`, `ff_*`, …)
- **Default voice**: `am_michael*0.7 + am_fenrir*0.3`
- **Languages**: American English (`en`), British English (`en-gb`), Spanish (`es`), French (`fr`), Hindi (`hi`), Italian (`it`), Portuguese (`pt`), Japanese (`ja`), Mandarin Chinese (`zh`)
- **Hardware**: Works on CPU, faster on GPU
- **Install**: `pip install sound-agent[kokoro]`

### Qwen3-TTS (Dual Model)
- **Package**: `qwen-tts>=0.1`
- **Models**:
  - `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` — voice design from description
  - `Qwen/Qwen3-TTS-12Hz-1.7B-Base` — stable voice cloning
- **Workflow**: VoiceDesign creates a reference → Base model clones it for every TTS → same voice every time
- **Voices**: Natural language voice descriptions (design any voice)
- **Cloning**: Optional `clone` config key pointing to a `.wav` file, with optional `ref_text` transcript
- **Reference cache**: `~/.cache/fast-market/sound/ref_voices/{voice_hash}.wav`
- **Languages**: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian
- **Hardware**: GPU recommended (2 × 1.7B param models)
- **Install**: `pip install sound-agent[qwen3]`

### MusicGen
- **Package**: `transformers` (included in base deps)
- **Model**: `facebook/musicgen-medium` (auto-downloaded on first use)
- **Generation**: Text-to-music with duration control
- **Hardware**: GPU recommended
- **Install**: `pip install sound-agent[musicgen]`

## Shell Completion

Shell completion (tab-completing engines, options, flags) is supported via Click's native completion.

```bash
# Show completion script for your shell
sound --show-completion

# Install (add to ~/.bashrc / ~/.zshrc / ~/.config/fish/config.fish)
sound --install-completion
```

Alternatively, manually add to your shell rc:

```bash
# bash
eval "$(_SOUND_COMPLETE=bash_source sound)"

# zsh
eval "$(_SOUND_COMPLETE=zsh_source sound)"

# fish
_SOUND_COMPLETE=fish_source sound | source
```

After installation, restart your shell or source the rc file. Options like `--engine` will tab-complete available engine names.

## Voice Mixing (Kokoro)

Kokoro supports weighted voice mixing by averaging voice embeddings. The syntax is:

```bash
# Single voice
sound speak "hello" --voice "am_michael"

# Equal mix (unweighted)
sound speak "hello" --voice "am_michael,am_fenrir"

# Weighted mix (70% Michael, 30% Fenrir)
sound speak "hello" --voice "am_michael*0.7,am_fenrir*0.3"
```

Weights are normalized so they always sum to 1.0. If some voices have weights and others don't, unweighted voices get equal share of the remaining weight.

## Project Structure

```
sound-cli/
├── sound_entry/           # CLI entry point (NOT cli/!)
│   └── __init__.py        # Imports main from cli.main
├── core/                  # Core logic (models, config)
├── plugins/               # Engine plugins
│   ├── base.py            # TTSPlugin + MusicGenPlugin ABCs
│   ├── kokoro/            # Kokoro TTS engine
│   ├── qwen3/             # Qwen3-TTS voice design engine
│   └── musicgen/          # MusicGen music engine
├── commands/              # CLI commands
│   ├── base.py            # CommandManifest
│   ├── helpers.py         # build_engine()
│   ├── speak/             # sound speak command
│   ├── music/             # sound music command
│   ├── prosody/           # sound prosody command (analysis.py + register.py)
│   ├── charisma/          # sound charisma command (analysis.py + register.py)
│   └── scoring.py         # shared target_band_score()/inverse_band_score() curves
└── common/                # Symlink to shared utilities
```

## Dependencies

### Core
- `click>=8.1` - CLI framework
- `pyyaml>=6.0` - config loading
- `soundfile>=0.12` - audio file I/O
- `torch>=2.0` - tensor operations
- `librosa>=0.10` - prosody/charisma analysis (pitch, energy, rhythm, voice quality)
- `ffmpeg` (system binary) - audio extraction from video for `sound prosody` / `sound charisma`

### Optional Engines
- `kokoro>=0.9` - Kokoro TTS (lightweight)
- `qwen-tts>=0.1` - Qwen3-TTS VoiceDesign
- `transformers` - MusicGen (included in core deps)

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run tests with coverage
pytest --cov=sound-cli tests/
```
