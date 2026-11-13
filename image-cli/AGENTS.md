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
├── webux/                 # Webux hub tab(s): yt_thumbnail (subprocess-driven)
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
| `qwen21/plugin.py` | `Qwen21EnginePlugin` - Qwen-Image-2.1 implementation (`QwenImage21Pipeline`; `guidance_scale` maps to `true_cfg_scale`, default 4.0/40 steps; `extra_pipe_kwargs` + `default_model_id` hooks for subclasses) |
| `qwen21/register.py` | Declares qwen21 plugin to the system |
| `qwen21turbo/plugin.py` | `Qwen21TurboEnginePlugin(Qwen21EnginePlugin)` - Turbo checkpoint (`Qwen/Qwen-Image-2.1-Turbo`), defaults 8 steps / CFG 1.0, `use_kv_cache=True` (silently retried without on old diffusers) |
| `qwen21turbo/register.py` | Declares qwen21turbo plugin to the system |

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
  qwen21:
    model_path: Qwen/Qwen-Image-2.1  # Hub ID; downloads on first use
    torch_dtype: bfloat16
    local_files_only: false
    quantization: null  # null = BF16 (~32GB RAM); "int8" = quanto (~16GB)
  qwen21turbo:
    model_path: Qwen/Qwen-Image-2.1-Turbo  # 8-step Turbo, CFG 1.0
    torch_dtype: bfloat16
    local_files_only: false
    quantization: null

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

## Pitfalls

- `flux2` is the local Klein engine. If `engines.flux2.model_path` is not a directory (and that repo is not in the Hugging Face cache), generation loads the local `black-forest-labs/FLUX.2-klein-4B` snapshot or `~/YouTools/flux2-klein-4b` instead of downloading the configured id.
- Cloudflare engines (`flux2cloud`, `flux29bcloud`, `flux3cloud`) read `account_id` / `api_token` from their own `engines.<name>` block, then `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`. A blank string in the active profile does not count as set. The webux process does not inherit a shell export unless those variables are in its environment or written into the profile. A reference image is unrelated: the credential check runs before the image is sent. The credentials are **shared between Cloudflare engines**: `ImageGenConfig.from_dict` fills a blank `account_id`/`api_token` from any configured sibling cloud engine (explicit per-engine values still win), and `image setup add <cloud-engine>` reuses a sibling's credentials instead of asking again — otherwise a profile that only configured `flux2cloud` fails on `flux3cloud` with “account_id is required”.
- YT Thumbnail has one **🎞️ Working video** selector at the top; it drives compose / edit / overlay / upload output, history, scene / title suggestions and push. With no video selected those actions keep writing `thumbnail_draft_*` in the video source directory — only “Push thumbnail to YouTube” actually requires a video, and it sends the thumbnail currently on screen.
- YT Thumbnail can also overlay an **external image**: `POST /upload-base` copies the picked file into the video folder as `<stem>_ext_<id>.<ext>` (image extensions only, dimensions returned so the UI can warn when it is not 1280×720). `window._pickedBase` then feeds `POST /overlay`, and the versioned output is pushed normally. The overlay worker only reuses the current version slot when the base *is* that version (`<stem>_thumb_<N>`); any imported/older base gets `_next_version()` so existing history is never overwritten.
- YT Thumbnail **adopts history images in place**: clicking a version in the history strip sets `window._pickedBase` (next overlay/edit) *and* `window._pickedThumb`, so “📥 Use as thumbnail” works without re-picking the file. A picked file still goes through `POST /upload-thumbnail` (copied to `<stem>_thumb_<N>`); a clicked version goes through `POST /adopt-thumbnail` (`{source, path}`), which only repoints `files.thumbnail`/`thumbnail_version` at the existing file — no copy, no new version. Both run through `_assert_inside`, so an out-of-root path is 403.
- Scene / overlay suggestions (`POST /suggest-scene`, `POST /suggest-overlay-title`) reuse `common.webux.transcripts.find_transcript()`; when nothing is on disk they run `video extract-transcript --format txt` first, honouring `youtube.publish.transcript_mode` (`groq` → `--use-groq`, `none` → refuse with a clear error). Prompt names come from `default_thumbnail_prompt` / `default_thumbnail_overlay_prompt`, falling back to `youtube-thumbnail` / `youtube-thumbnail-title`. Both are background jobs (Whisper can take 10+ min) and write `thumbnail_prompt` / `thumbnail_overlay_title` into the shared `*-long-meta.json`, so Long Publish and this tab share one suggestion. Each job runs under the meta's `profile` (`FASTMARKET_PROFILE`) because prompts and YouTube credentials are per profile.

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
