from __future__ import annotations

from pathlib import Path

from common.core.config import load_tool_config

from core.models import ImageGenConfig


def load_image_config(path: str | None = None) -> ImageGenConfig:
    """Load and validate image-agent config."""
    raw = load_tool_config("image", path)
    return ImageGenConfig.from_dict(raw)


def get_default_config() -> dict:
    """Return default config as a dict (for setup wizard)."""
    return {
        "default_engine": "flux2",
        "engines": {
            "flux2": {
                "model_path": "./flux2-klein-4b",
                "torch_dtype": "bfloat16",
                "local_files_only": True,
            },
            "qwen21": {
                "model_path": "Qwen/Qwen-Image-2.1",
                "torch_dtype": "bfloat16",
                "local_files_only": False,
                # null = full precision (~32GB RAM); "int8" = quanto int8
                # for transformer + text encoder (~16GB RAM). Recommended
                # for GPUs with <24GB VRAM / machines with <64GB RAM.
                "quantization": None,
            },
            "qwen21turbo": {
                "model_path": "Qwen/Qwen-Image-2.1-Turbo",
                "torch_dtype": "bfloat16",
                "local_files_only": False,
                # Same backends as qwen21 (null/int8/int4). Turbo's
                # recommended schedule is 8 steps at CFG 1.0 — pass
                # -S/-g explicitly to deviate from it.
                "quantization": None,
            },
            "flux2cloud": {
                "account_id": "",
                "api_token": "",
                # "@cf/black-forest-labs/flux-2-klein-4b" or
                # "@cf/black-forest-labs/flux-2-klein-9b"
                # (9B: fixed 4 steps, higher quality).
                "cf_model": "@cf/black-forest-labs/flux-2-klein-4b",
            },
            "flux29bcloud": {
                "account_id": "",
                "api_token": "",
                # Pinned to 9B (fixed 4 steps, higher quality). The plugin
                # forces this value; kept here for visibility / credentials.
                "cf_model": "@cf/black-forest-labs/flux-2-klein-9b",
            },
        },
        "default_width": 1024,
        "default_height": 1024,
        "default_guidance_scale": 1.0,
        "default_num_inference_steps": 4,
        "default_output_format": "PNG",
        "default_seed": None,
        "output_dir": ".",
        "cache_pipeline": True,
        "force_device": None,
        "overlay": {
            "font": "Tomorrow",
            "vpos": "bottom",
            "hpos": "center",
            "size": "fit",
            "fg": "blue",
            "bg": "light green",
            "effect": "band",
            "style": "normal",
            "band_size": 8,
        },
        "available_sizes": [
            {"name": "square", "width": 1024, "height": 1024},
            {"name": "portrait", "width": 768, "height": 1024},
            {"name": "landscape", "width": 1024, "height": 768},
            {"name": "youtube", "width": 1280, "height": 720},
            {"name": "wide", "width": 1024, "height": 576},
            {"name": "tall", "width": 576, "height": 1024},
        ],
        "available_formats": ["PNG", "JPEG", "WEBP"],
    }
