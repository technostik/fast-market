from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import torch
from PIL import Image

from core.models import ImageGenConfig, ImageGenRequest, ImageGenResult
from plugins.base import ImageEnginePlugin


class ImageGenEngine:
    """Orchestrator for image generation across multiple engines."""

    def __init__(
        self,
        plugins: dict[str, ImageEnginePlugin],
        config: ImageGenConfig,
    ):
        self.plugins = plugins
        self.config = config

    def generate(
        self,
        request: ImageGenRequest,
        output_dir: str | None = None,
    ) -> ImageGenResult:
        """Generate an image and save it to disk."""
        engine_name = request.engine or self.config.default_engine
        if engine_name not in self.plugins:
            raise ValueError(
                f"Unknown engine: {engine_name}. Available: {list(self.plugins.keys())}"
            )

        plugin = self.plugins[engine_name]

        if request.init_image is not None and not plugin.supports_img2img():
            raise ValueError(
                f"Engine {engine_name} does not support img2img (init_image)"
            )

        if not plugin.supports_seeds() and request.seed is not None:
            raise ValueError(f"Engine {engine_name} does not support seeds")

        start_time = time.time()

        seed = request.seed
        if seed is None and self.config.default_seed is not None:
            seed = self.config.default_seed

        request = ImageGenRequest(
            prompt=request.prompt,
            width=request.width,
            height=request.height,
            guidance_scale=request.guidance_scale,
            num_inference_steps=request.num_inference_steps,
            seed=seed,
            init_image=request.init_image,
            strength=request.strength,
            output_format=request.output_format,
            engine=engine_name,
        )

        image = plugin.generate(request)

        output_format = request.output_format or self.config.default_output_format
        output_dir_path = Path(output_dir or self.config.output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        actual_seed = request.seed or 0
        filename = f"{engine_name}_{actual_seed}.{output_format.lower()}"
        filepath = output_dir_path / filename

        image.save(filepath, format=output_format)

        generation_time = time.time() - start_time

        return ImageGenResult(
            path=str(filepath.absolute()),
            seed=actual_seed,
            width=request.width,
            height=request.height,
            engine=engine_name,
            prompt=request.prompt,
            output_format=output_format,
            generation_time=generation_time,
        )

    def list_engines(self) -> list[str]:
        """List available engine names."""
        return list(self.plugins.keys())

    def get_engine(self, name: str) -> ImageEnginePlugin | None:
        """Get a specific engine by name."""
        return self.plugins.get(name)

    def validate_engines(self) -> dict[str, bool]:
        """Validate that all configured engines have valid model paths."""
        results = {}
        for name, plugin in self.plugins.items():
            engine_config = self.config.get_engine_config(name)
            results[name] = plugin.validate_model_path(engine_config.model_path)
        return results
