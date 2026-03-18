from __future__ import annotations

import random
from typing import Any, TYPE_CHECKING

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin

if TYPE_CHECKING:
    import torch
    from diffusers import Flux2KleinPipeline


class Flux2EnginePlugin(ImageEnginePlugin):
    """FLUX.2 Klein image generation engine."""

    name = "flux2"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config
        self._pipeline: "Flux2KleinPipeline | None" = None
        self._device: str | None = None

    def _get_device(self) -> str:
        """Determine device to use (cuda/cpu)."""
        if self._device:
            return self._device
        if self.config.force_device:
            return self.config.force_device
        import torch

        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load_pipeline(self, cache: bool = True) -> "Flux2KleinPipeline":
        """Load the FLUX.2 pipeline."""
        if cache and self._pipeline is not None:
            return self._pipeline

        import torch
        from diffusers import Flux2KleinPipeline

        torch_dtype = torch.bfloat16
        if self.config.torch_dtype == "float16":
            torch_dtype = torch.float16
        elif self.config.torch_dtype == "float32":
            torch_dtype = torch.float32

        pipe = Flux2KleinPipeline.from_pretrained(
            self.config.model_path,
            torch_dtype=torch_dtype,
            local_files_only=self.config.local_files_only,
        )

        device = self._get_device()
        if device == "cuda":
            pipe.enable_sequential_cpu_offload()
        else:
            pipe.to(device)

        self._device = device
        self._pipeline = pipe
        return pipe

    def _unload_pipeline(self) -> None:
        """Unload the pipeline to free memory."""
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def generate(self, request: ImageGenRequest) -> Image.Image:
        """Generate an image using FLUX.2 Klein."""
        import torch

        pipe = self._load_pipeline(cache=self.config.model_path != "")

        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)

        generator = torch.Generator(device=self._get_device()).manual_seed(seed)

        pipe_params: dict[str, Any] = {
            "prompt": request.prompt,
            "height": request.height,
            "width": request.width,
            "guidance_scale": request.guidance_scale,
            "num_inference_steps": request.num_inference_steps,
            "generator": generator,
        }

        if request.init_image is not None:
            pipe_params["image"] = request.init_image
            if request.strength is not None:
                pipe_params["strength"] = request.strength

        result = pipe(**pipe_params)
        return result.images[0]

    def supports_img2img(self) -> bool:
        return True

    def supports_seeds(self) -> bool:
        return True

    def get_default_size(self) -> tuple[int, int]:
        return (1024, 1024)

    def get_default_steps(self) -> int:
        return 4

    def get_default_guidance_scale(self) -> float:
        return 1.0

    def validate_model_path(self) -> bool:
        """Validate that the FLUX.2 model path exists."""
        if not self.config.model_path:
            return False
        return super().validate_model_path(self.config.model_path)
