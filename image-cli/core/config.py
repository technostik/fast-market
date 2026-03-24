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
            }
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
