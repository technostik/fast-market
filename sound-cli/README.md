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

qwen3:
  voice: "A warm, friendly male voice with a professional tone"
  language: English
  model: Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign

musicgen:
  model: facebook/musicgen-medium
  duration: 5.0

output_format: wav
```

Output files are written to the common config `workdir` (set in `~/.config/fast-market/common/config.yaml`).

## Commands

| Command | Description |
|---------|-------------|
| `sound speak "text"` | Synthesize speech from text |
| `sound speak "text" -e qwen3 -v "description"` | TTS with voice design |
| `sound speak "text" -e kokoro -v "am_michael" --speed 1.5` | Kokoro with options |
| `sound music "lofi piano track"` | Generate music from prompt |
| `sound music "upbeat electronic" -d 10` | Music with custom duration |

### `sound speak <TEXT>`

Synthesize speech from text using a TTS engine.

| Option | Short | Description |
|--------|-------|-------------|
| `--engine` | `-e` | TTS engine: `kokoro` or `qwen3` (from config) |
| `--voice` | `-v` | Voice spec (semantics depend on engine) |
| `--speed` | `-s` | Playback speed, default 1.0 (kokoro only) |
| `--output` | `-o` | Output path (default: workdir/speak\_\<timestamp\>.wav) |
| `--language` | `-L` | Language for qwen3 (English, Chinese, etc.) |
| `--format` | `-F` | Output format: `json` or `text` |

**Voice semantics by engine:**
- **kokoro**: Weighted voice mix. Format: `name[*weight,...]`. Example: `am_michael*0.7,am_fenrir*0.3`. Weights are normalized to sum to 1.0. A single name like `am_michael` uses that voice directly.
- **qwen3**: Natural language voice description. Example: `"A soft, elegant French female voice"`. Pairs with `--language` for multilingual generation.

### `sound music <PROMPT>`

Generate music from a text prompt.

| Option | Short | Description |
|--------|-------|-------------|
| `--engine` | `-e` | Music engine: `musicgen` |
| `--duration` | `-d` | Duration in seconds, default 5.0 |
| `--output` | `-o` | Output path (default: workdir/music\_\<timestamp\>.wav) |
| `--format` | `-F` | Output format: `json` or `text` |

## Engines

### Kokoro (TTS)
- **Package**: `kokoro>=0.9`
- **Model**: `hexgrad/Kokoro-82M` (auto-downloaded on first use)
- **Voices**: American English voices (`am_*`) with weighted mixing
- **Default voice**: `am_michael*0.7 + am_fenrir*0.3`
- **Hardware**: Works on CPU, faster on GPU
- **Install**: `pip install sound-agent[kokoro]`

### Qwen3-TTS VoiceDesign
- **Package**: `qwen-tts>=0.1`
- **Model**: `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` (auto-downloaded on first use)
- **Voices**: Natural language voice descriptions (design any voice)
- **Languages**: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian
- **Hardware**: GPU recommended (1.7B param model)
- **Install**: `pip install sound-agent[qwen3]`

### MusicGen
- **Package**: `transformers` (included in base deps)
- **Model**: `facebook/musicgen-medium` (auto-downloaded on first use)
- **Generation**: Text-to-music with duration control
- **Hardware**: GPU recommended
- **Install**: `pip install sound-agent[musicgen]`

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
│   └── music/             # sound music command
└── common/                # Symlink to shared utilities
```

## Dependencies

### Core
- `click>=8.1` - CLI framework
- `pyyaml>=6.0` - config loading
- `soundfile>=0.12` - audio file I/O
- `torch>=2.0` - tensor operations

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
