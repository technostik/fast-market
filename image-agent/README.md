# image-agent

AI image generation CLI tool with FLUX.2 support. Generate images from text prompts using multiple engine plugins, with both CLI and API interfaces.

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
- Adding image generation engines (FLUX.2)
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

default_width: 1024
default_height: 1024
default_guidance_scale: 1.0
default_num_inference_steps: 4
default_output_format: PNG                 # PNG, JPEG, or WEBP
default_seed: null                         # null = random
output_dir: "./generated"
cache_pipeline: true                        # Cache model in memory
force_device: null                          # null = auto, "cuda", or "cpu"

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

## CLI Reference

### `image generate`

Generate an image from a text prompt.

```bash
image generate "a serene mountain landscape at sunset" [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--engine, -e` | Engine to use (flux2) | from config |
| `--size, -s` | Size preset (square/portrait/landscape/youtube/wide/tall/custom) | square |
| `--width, -w` | Image width (overrides size) | from config |
| `--height, -h` | Image height (overrides size) | from config |
| `--guidance-scale, -g` | Guidance scale | from config |
| `--steps` | Number of inference steps | from config |
| `--seed` | Random seed for reproducibility | random |
| `--init-image` | Path to initial image for img2img | None |
| `--keep-original-size` | Keep original size of init image | False |
| `--strength` | Strength for img2img (0.0-1.0) | None |
| `--output-format, -f` | Output format (PNG/JPEG/WEBP) | from config |
| `--output-dir, -o` | Output directory | from config |
| `--format` | Output format for CLI (json/text) | text |
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

# JSON output for scripting
image generate "minimalist logo" --format json | jq '.path'

# Generate multiple variations with xargs
seq 1 5 | xargs -I {} image generate "variation {} of abstract pattern" --format json | jq -r '.path' | xargs open
```

### `image setup`

Configure image-agent interactively or non-interactively.

```bash
image setup [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--list-engines` | List configured engines |
| `--add-engine` | Add an engine (flux2) |
| `--remove-engine` | Remove an engine |
| `--set-default-engine` | Set default engine |
| `--set-model-path` | Set model path (format: engine:path) |
| `--set-defaults` | Set generation defaults interactively |
| `--set-output-dir` | Set default output directory |
| `--show-config` | Show current configuration |
| `--show-config-path` | Show config file path |

**Examples:**

```bash
# Run interactive wizard
image setup

# Add engine non-interactively
image setup --add-engine flux2 --set-model-path flux2:/path/to/model

# View current configuration
image setup --show-config

# Set default output directory
image setup --set-output-dir ~/Pictures/generated
```

### `image serve`

Start the FastAPI server for HTTP access.

```bash
image serve [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--host` | Host to bind to | 127.0.0.1 |
| `--port` | Port to bind to | 8000 |

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
│   └── flux2/            # FLUX.2 implementation
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
