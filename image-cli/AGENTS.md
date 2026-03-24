# image-agent

## Purpose
AI image generation CLI tool with FLUX.2 support. Provides a modular plugin system for multiple image generation engines with CLI, API, and configuration management.

## Architecture Overview

```
image-agent/
├── image_entry/           # CLI entry point (NOT cli/!)
│   └── __init__.py        # Imports main from cli.main
├── core/                  # Core logic (models, engine, config)
├── plugins/               # Image engine plugins (flux2)
├── commands/              # CLI commands (generate, setup, serve)
├── api/                   # FastAPI server
└── common/                # Symlink to shared utilities
```

## Essential Components

### Core (`core/`)

| File | Purpose |
|------|---------|
| `models.py` | `ImageGenRequest`, `ImageGenResult`, `ImageGenConfig`, `ImageSize`, `EngineConfig` dataclasses |
| `engine.py` | `ImageGenEngine` - orchestrates generation across plugins |
| `config.py` | Config loading and default values |

### Plugins (`plugins/`)

| File | Purpose |
|------|---------|
| `base.py` | `ImageEnginePlugin` ABC, `PluginManifest` |
| `flux2/plugin.py` | `Flux2EnginePlugin` - FLUX.2 Klein implementation |
| `flux2/register.py` | Declares flux2 plugin to the system |

### Commands (`commands/`)

| File | Purpose |
|------|---------|
| `base.py` | `CommandManifest` dataclass |
| `helpers.py` | `build_engine()`, logging configuration |
| `generate/` | `image generate` command |
| `setup/` | `image setup` wizard |
| `serve/` | `image serve` API server command |

### API (`api/`)

| File | Purpose |
|------|---------|
| `server.py` | FastAPI application with /generate, /health, /engines endpoints |

## Core Responsibilities

### Image Generation
- Accept text prompts with generation parameters
- Support img2img (init_image) for variation/editing
- Generate images using configured engine plugins
- Save images to configurable output directory
- Return generation metadata (path, seed, timing)

### Plugin System
- Auto-discover plugins from `plugins/*/register.py`
- Support multiple image engines (flux2, etc.)
- Each plugin implements `ImageEnginePlugin` ABC
- Plugins can inject CLI options into commands

### Configuration
- XDG-compliant config path: `~/.config/fast-market/image/config.yaml`
- Interactive setup wizard for configuration
- Engine-specific settings (model paths, dtype)
- Default generation parameters (size, steps, guidance)

### API Server
- Full generation with all parameters
- Health check and engine listing endpoints
- Cached pipelines for persistent server mode

## Configuration Schema

```yaml
# ~/.config/fast-market/image/config.yaml

default_engine: flux2

engines:
  flux2:
    model_path: ./flux2-klein-4b  # Configurable!
    torch_dtype: bfloat16
    local_files_only: true

default_width: 1024
default_height: 1024
default_guidance_scale: 1.0
default_num_inference_steps: 4
default_output_format: PNG
default_seed: null  # null = random
output_dir: "."
cache_pipeline: true  # true for server, false for CLI
force_device: null    # null = auto, "cuda", or "cpu"

available_sizes:
  - name: square
    width: 1024
    height: 1024
  - name: portrait
    width: 768
    height: 1024
  # ...

available_formats:
  - PNG
  - JPEG
  - WEBP
```

## Commands

| Command | Description |
|---------|-------------|
| `image generate "prompt"` | Generate image from text |
| `image generate "prompt" -s portrait -S 8` | With options |
| `image setup` | Interactive setup wizard |
| `image setup -a flux2` | Add engine non-interactively |
| `image setup -c` | Display current config |
| `image serve -p 8080` | Start API server |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/generate` | POST | Generate image |
| `/engines` | GET | List available engines |
| `/engines/{name}/validate` | GET | Validate engine config |
| `/config` | GET | Get current configuration |

## Dependencies & Integration

### External Dependencies
- `torch`, `diffusers`, `transformers` - image generation
- `click` - CLI framework
- `fastapi`, `uvicorn` - API server
- `pyyaml` - config loading
- `Pillow` - image handling

### Integrations
- Imports from `common/` (cli, core, registry)
- Plugin system mirrors corpus-agent pattern
- Config uses XDG paths from common

## Do's

- Use `build_engine()` from helpers to construct engine
- Use `ImageGenConfig.from_dict()` for config loading
- Use `out()` from helpers for consistent output
- Validate engine support before using features (img2img, seeds)
- Use `**kwargs` to absorb plugin-injected options

## Don'ts

- Hardcode plugin names - use manifests
- Hardcode paths - use XDG from common
- Cache pipeline in CLI mode (use `cache_pipeline=False`)
- Swallow exceptions - FAIL LOUDLY
- Use global state for engine instances

## Extension Points

### Add New Image Engine

1. Create `plugins/your_engine/plugin.py` implementing `ImageEnginePlugin`
2. Create `plugins/your_engine/register.py` returning `PluginManifest`
3. Add engine config defaults to `core/config.py`

### Add New CLI Command

1. Create `commands/your_command/` with `__init__.py` and `register.py`
2. Implement `register(plugin_manifests) -> CommandManifest`
3. Registry auto-discovers and registers

### Add API Endpoints

1. Add route to `api/server.py`
2. Or provide `api_router` in `CommandManifest`

## Related Documentation

- See `.doc/GOLDEN_RULES.md` for architectural principles
- See `common/core/registry.py` for plugin discovery
