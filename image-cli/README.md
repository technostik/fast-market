# image-agent

AI image generation CLI tool with FLUX.2 and Qwen-Image-2.1 support. Generate images from text prompts using multiple engine plugins, with both CLI and API interfaces.

## Installation

```bash
# Install from source
cd image-agent
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"
```

### Prerequisites

- Python 3.11 or higher
- CUDA-compatible GPU recommended for optimal performance
- Model files for FLUX.2 (download separately)

## Configuration

Configuration is stored in XDG-compliant paths:
- **Config file**: `~/.local/share/fast-market/config/image.yaml`
- **Cache directory**: `~/.cache/fast-market/image/`

### First-time Setup

Run the interactive setup wizard to configure your engines and defaults:

```bash
image setup
```

The wizard guides you through:
- Adding image generation engines (FLUX.2, Qwen-Image-2.1)
- Setting model paths
- Configuring default generation parameters
- Setting output directory

### Configuration File

```yaml
# ~/.local/share/fast-market/config/image.yaml

default_engine: flux2

engines:
  flux2:
    model_path: /path/to/flux2-klein-4b  # Required: path to model
    torch_dtype: bfloat16                 # bfloat16, float16, or float32
    local_files_only: true                 # Don't try to download
  qwen21:
    model_path: Qwen/Qwen-Image-2.1      # Hub ID, downloaded on first use
    torch_dtype: bfloat16
    local_files_only: false
    quantization: null                   # null = full precision (~32GB RAM);
                                         # "int8" = 8-bit (~16GB), "int4" = NF4 (~9GB)

default_width: 1024
default_height: 1024
default_guidance_scale: 1.0
default_num_inference_steps: 4
default_output_format: PNG                 # PNG, JPEG, or WEBP
default_seed: null                         # null = random
output_dir: "./generated"
cache_pipeline: true                        # Cache model in memory
force_device: null                          # null = auto, "cuda", or "cpu"

# Text overlay defaults (used when --title is provided)
overlay:
  font: Tomorrow                            # Font family; falls back to DejaVuSans then PIL default
  vpos: bottom                              # top / middle / bottom
  hpos: center                              # left / center / right
  size: fit                                 # integer font size or "fit"
  fg: blue                                  # text color (name, hex, or "none")
  bg: light green                           # effect color (name, hex, or "none" to disable)
                                           # hex in YAML: use "ff0000" or 0xff0000 (not #ff0000)
  effect: band                              # none / box / shadow / band
  style: normal                             # normal / bold / italic / bold-italic
  band_size: 8                             # band height as % of image height (band effect only)

available_sizes:
  - name: square
    width: 1024
    height: 1024
  - name: portrait
    width: 768
    height: 1024
  - name: landscape
    width: 1024
    height: 768
  - name: youtube
    width: 1280
    height: 720
  - name: wide
    width: 1024
    height: 576
  - name: tall
    width: 576
    height: 1024

available_formats:
  - PNG
  - JPEG
  - WEBP
```

### Obtaining Models

FLUX.2 Klein model files must be downloaded separately:
1. Visit [FLUX.2 model page](https://huggingface.co/black-forest-labs/FLUX.1-dev) (or appropriate source)
2. Download the model files to a local directory
3. Set `model_path` in config to that directory

Qwen-Image-2.1 weights download automatically from the Hub
(`Qwen/Qwen-Image-2.1`, ~7B params) on first use. Requirements:
`transformers>=5.17`, `accelerate`, and a CUDA GPU
with ample VRAM — plus **pre-release diffusers from git main**
(`pip install git+https://github.com/huggingface/diffusers`), because
`QwenImage21Pipeline` is not yet in any PyPI release (checked up to 0.40).
The model is under the Qwen Research license, which may
require accepting terms on HuggingFace and `hf auth login`.

#### VRAM / RAM footprint

The full-precision pipeline is ~32GB (7B DiT + large Qwen3-VL text encoder
in BF16) — it needs ~32GB system RAM but runs on 8GB VRAM cards: on CUDA
the plugin enables sequential CPU offload (layer-by-layer streaming) plus
attention slicing and VAE tiling. Verified on an 8GB RTX 4060 Laptop
(512px/4 steps in ~50s, 1024px/40 steps in ~11min).

Optional weight quantization (`quantization: int8` = 8-bit, `int4` = NF4)
lowers RAM to ~16GB/~9GB. Backend is picked automatically: bitsandbytes on
CUDA (`pip install bitsandbytes`), quanto on CPU (`pip install
optimum-quanto`). Two hard lessons encoded in the loader, don't regress:
- the pipeline-level device map places *whole components* — a 7GB
  transformer never fits a small GPU that way; components must be handled
  individually or streamed with offload hooks;
- quanto tensors cannot be rebuilt from the meta device used by offload
  hooks or device maps (hence bnb, not quanto, on CUDA);
- bitsandbytes refuses CPU/disk-dispatched modules without fp32 CPU
  offload, and its quantization runs on GPU — so bnb components load
  plainly and are streamed with sequential offload, never statically
  dispatched to CPU.

## CLI Reference

### `image generate`

Generate an image from a text prompt.

```bash
image generate "a serene mountain landscape at sunset" [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-e, --engine` | Engine to use (flux2/flux2cloud/qwen21) | from config |
| `-s, --size` | Size preset (square/portrait/landscape/youtube/wide/tall/custom) | from config (`default_width`/`default_height`) |
| `-w, --width` | Image width (overrides size) | from config |
| `-h, --height` | Image height (overrides size) | from config |
| `-g, --guidance-scale` | Guidance scale (qwen21 maps this to `true_cfg_scale`, default 4.0) | from config |
| `-S, --steps` | Number of inference steps | from config |
| `-d, --seed` | Random seed for reproducibility | random |
| `-i, --init-image` | Path to initial image for img2img | None |
| `--keep-original-size` | Keep original size of init image | False |
| `-t, --strength` | Strength for img2img (0.0-1.0) | None |
| `--output-format` | Output format (PNG/JPEG/WEBP) | from config |
| `-o, --output-dir` | Output directory | from config |
| `-F, --format` | Output format for CLI (json/text) | text |
| `-T, --title` | Text to superimpose on the image (a title) | None |
| `--position` | Text position: `top-left`/`top-center`/`top-right`/`middle-left`/`middle-center`/`middle-right`/`bottom-left`/`bottom-center`/`bottom-right` | bottom-center |
| `--overlay-size` | Font size: an integer (e.g. `48`) or `fit` to auto-scale to the image | fit |
| `--overlay-fg` | Foreground (text) color name or hex | blue |
| `--overlay-bg` | Background effect color name/hex, or `none` to disable | light green |
| `--overlay-effect` | Background effect: `none`/`box`/`shadow`/`band` | band |
| `--overlay-style` | Font style: `normal`/`bold`/`italic`/`bold-italic` | normal |
| `--overlay-band-size` | Band height as % of image height (band effect) | 8 |
| `-v, --verbose` | Enable verbose logging | |

**Examples:**

```bash
# Basic generation
image generate "cyberpunk city with neon lights"

# Use size preset with custom steps
image generate "fantasy dragon" --size landscape --steps 8

# Set specific seed for reproducibility
image generate "abstract art" --seed 42 --width 768 --height 768

# Generate variation from existing image
image generate "make it sunset" --init-image photo.jpg --strength 0.7

# Generate with Qwen-Image-2.1 (uses true_cfg_scale 4.0 / 40 steps)
image generate "a neon shop sign, rainy night" -e qwen21 -g 4.0 -S 40

# JSON output for scripting
image generate "minimalist logo" -F json | jq '.path'

# Generate multiple variations with xargs
seq 1 5 | xargs -I {} image generate "variation {} of abstract pattern" --format json | jq -r '.path' | xargs open
```

### Fonts

Text overlay uses a TrueType/OpenType font. The default family is `Tomorrow`; if it
is not installed, the loader falls back to `DejaVuSans` (usually present), then to
PIL's built-in bitmap font.

Fonts are resolved via **fontconfig** (`fc-match`), so any font installed on the
system works by its real family name (the loader also falls back to a filesystem
search of these directories, then to `DejaVuSans`, then to PIL's default):

- `/usr/share/fonts`
- `/usr/local/share/fonts`
- `~/.fonts`
- `~/.local/share/fonts`

To install a font (e.g. Tomorrow), copy the `.ttf`/`.otf` files into one of those
directories:

```bash
mkdir -p ~/.fonts
cp Tomorrow-Regular.ttf ~/.fonts/
# optional, for style variants:
cp Tomorrow-Bold.ttf Tomorrow-Italic.ttf Tomorrow-BoldItalic.ttf ~/.fonts/
fc-cache -f   # refresh the fontconfig cache (recommended)
```

For **style** variants, name the files `Family-Bold`, `Family-Italic`, and
`Family-BoldItalic` (e.g. `Tomorrow-Bold.ttf`). If a variant is missing the loader
falls back to the base family gracefully.

**Console feedback:** the command prints `Using font: <path>` (to stderr) so you can
see exactly which font file was selected, and a `Warning:` if the configured
`overlay.font` family cannot be resolved (it then falls back to `DejaVuSans`/PIL
default). To check a family name before configuring it, run `fc-match '<name>'`.

Colors for `--overlay-fg` / `--overlay-bg` accept X11 color names (spaces normalized,
e.g. `light green`), `#rgb` / `#rrggbb` hex codes, `0x`-prefixed hex, or bare hex
(`rrggbb` / `rgb`), or `none` (disables the effect).

> **YAML caveat:** in the config file a leading `#` starts a comment, so a value like
> `fg: #ff0000` is read as empty. Either quote it (`fg: "#ff0000"`) or use a form that
> needs no quoting: `fg: 0xff0000` or `fg: ff0000`.

### `image overlay`

Add superimposed text (a title) onto an **existing** image and write a new image.
Takes the same overlay options as `image generate`; defaults come from the `overlay:`
config group.

```bash
image overlay INPUT_IMAGE --title "My Title" [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `IMAGE` (argument) | Path to the existing image | (required) |
| `-T, --title` | Text to superimpose | (required) |
| `--position` | `top/middle/bottom` + `left/center/right` (9 combos) | bottom-center |
| `-o, --output` | Output image path (default: `<input>_overlay<ext>`) | derived |
| `--overlay-size` | Font size: integer or `fit` | fit |
| `--overlay-fg` | Text color (name/hex/`none`) | blue |
| `--overlay-bg` | Effect color (name/hex/`none`) | light green |
| `--overlay-effect` | `none`/`box`/`shadow`/`band` | band |
| `--overlay-style` | `normal`/`bold`/`italic`/`bold-italic` | normal |
| `--overlay-band-size` | Band height as % of image height | 8 |
| `-F, --format` | Output format (json/text) | text |

**Examples:**
```bash
# Add a banded title to an existing photo
image overlay photo.jpg --title "Summer 2024" --overlay-effect band

# Bold, boxed title, custom color, explicit output
image overlay logo.png --title "SALE" --overlay-style bold \
  --overlay-effect box --overlay-fg "#ffffff" --overlay-bg ff0000 -o out.png
```

### `image setup`

Configure image-agent. `setup` is a command group with subcommands:

```bash
image setup [SUBCOMMAND] [OPTIONS]
```

| Subcommand | Description |
|------------|-------------|
| `wizard` | Run the interactive wizard (engines, defaults, output dir) |
| `show` | Show current configuration (`--path` for path only, `--engines` for engines only) |
| `edit` | Open the config file in your default editor |
| `reset` | Reset config to defaults (backs up existing config) |
| `engine add` | Add an engine (`--engine flux2`) |
| `engine remove ENGINE` | Remove an engine |
| `engine set-default ENGINE` | Set the default engine |
| `engine set-model-path ENGINE:PATH` | Set an engine's model path |

**Examples:**

```bash
# Run interactive wizard
image setup wizard

# Show config / path / engines
image setup show
image setup show --path
image setup show --engines

# Edit config in editor
image setup edit

# Reset to defaults
image setup reset

# Manage engines
image setup engine add --engine flux2
image setup engine set-model-path flux2:/path/to/model
image setup engine set-default flux2
image setup engine remove flux2
```

### `image serve`

Start the FastAPI server for HTTP access.

```bash
image serve [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `-H, --host` | Host to bind to | 127.0.0.1 |
| `-p, --port` | Port to bind to | 8000 |

**Example:**

```bash
# Start server on all interfaces
image serve --host 0.0.0.0 --port 8080
```

## API Reference

### Generate Image

```bash
POST /generate
```

**Request body:**
```json
{
  "prompt": "a serene mountain landscape at sunset",
  "width": 1024,
  "height": 1024,
  "guidance_scale": 1.0,
  "num_inference_steps": 4,
  "seed": 42,
  "init_image_base64": "base64-encoded-image-data",
  "strength": 0.7,
  "output_format": "PNG",
  "engine": "flux2"
}
```

**Response:**
```json
{
  "path": "/absolute/path/to/generated/image.png",
  "seed": 42,
  "width": 1024,
  "height": 1024,
  "engine": "flux2",
  "prompt": "a serene mountain landscape at sunset",
  "output_format": "PNG",
  "generation_time": 2.345
}
```

### Health Check

```bash
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "engines": ["flux2"]
}
```

### List Engines

```bash
GET /engines
```

**Response:**
```json
{
  "engines": ["flux2"],
  "default": "flux2"
}
```

### Validate Engine

```bash
GET /engines/{engine_name}/validate
```

**Response:**
```json
{
  "engine": "flux2",
  "valid": true,
  "model_path": "/path/to/flux2-klein-4b"
}
```

### Get Configuration

```bash
GET /config
```

**Response:**
```json
{
  "default_engine": "flux2",
  "default_width": 1024,
  "default_height": 1024,
  "default_guidance_scale": 1.0,
  "default_num_inference_steps": 4,
  "default_output_format": "PNG",
  "output_dir": ".",
  "available_sizes": [...],
  "available_formats": ["PNG", "JPEG", "WEBP"],
  "engines": {
    "flux2": {"model_path": "/path/to/model"}
  }
}
```

## Features

- **Multiple Engine Support**: Plugin architecture for different image generation engines
- **Img2Img**: Generate variations from existing images
- **Size Presets**: Common aspect ratios (square, portrait, landscape, YouTube, wide, tall)
- **Reproducible Generation**: Set seeds for consistent results
- **Flexible Output**: PNG, JPEG, or WEBP formats
- **API Server**: FastAPI server for HTTP access
- **Interactive Setup**: Guided configuration wizard
- **JSON Output**: Script-friendly output format

## Architecture

```
image-agent/
├── image_entry/           # CLI entry point
├── core/                  # Core logic
│   ├── models.py         # Request/result dataclasses
│   ├── engine.py         # Generation orchestrator
│   └── config.py         # Config loading
├── plugins/               # Image engine plugins
│   ├── base.py           # Plugin ABC and manifest
│   ├── flux2/            # FLUX.2 implementation
│   └── qwen21/           # Qwen-Image-2.1 implementation
├── commands/              # CLI commands
│   ├── generate/         # image generate
│   ├── setup/            # image setup
│   └── serve/            # image serve
├── api/                   # FastAPI server
└── common/                # Shared utilities (symlink)
```

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/
```

### Adding a New Engine

1. Create plugin directory:
```bash
mkdir -p plugins/your_engine
```

2. Implement engine plugin (`plugins/your_engine/plugin.py`):
```python
from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin

class YourEnginePlugin(ImageEnginePlugin):
    name = "your_engine"

    def __init__(self, config: EngineConfig | dict):
        # Initialize

    def generate(self, request: ImageGenRequest) -> Image.Image:
        # Generate image

    def supports_img2img(self) -> bool:
        return False  # or True if supported

    def supports_seeds(self) -> bool:
        return True

    def get_default_size(self) -> tuple[int, int]:
        return (1024, 1024)

    def get_default_steps(self) -> int:
        return 4

    def get_default_guidance_scale(self) -> float:
        return 1.0
```

3. Register plugin (`plugins/your_engine/register.py`):
```python
from plugins.base import PluginManifest
from plugins.your_engine.plugin import YourEnginePlugin

def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="your_engine",
        engine_class=YourEnginePlugin,
        cli_options={},  # Add CLI options if needed
        api_router=None,  # Add API routes if needed
    )
```

### Adding a New CLI Command

1. Create command directory:
```bash
mkdir -p commands/your_command
```

2. Implement command (`commands/your_command/register.py`):
```python
import click
from commands.base import CommandManifest

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("your-command")
    @click.option("--option")
    @click.pass_context
    def your_cmd(ctx, option):
        """Command description."""
        # Implementation

    return CommandManifest(
        name="your-command",
        click_command=your_cmd,
        api_router=None,  # Optional API routes
    )
```

### Adding Plugin CLI Options

Plugins can inject options into existing commands:

```python
# In plugin's register.py
from click import Option

def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="your_engine",
        engine_class=YourEnginePlugin,
        cli_options={
            "generate": [  # Add to 'generate' command
                Option(["--your-option"], help="Your option")
            ],
            "*": [  # Add to ALL commands
                Option(["--global-option"], help="Global option")
            ]
        },
    )
```
