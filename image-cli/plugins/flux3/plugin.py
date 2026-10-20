from __future__ import annotations

import random
from typing import Any

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin


class Flux3EnginePlugin(ImageEnginePlugin):
    """FLUX.3 Image Klein (distilled) via diffusers ModularPipeline (local)."""

    name = "flux3"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config
        self._pipe = None

    def _load_pipe(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import BFLQuantizationConfig, Flux3Transformer2DModel
        from diffusers.modular_pipelines.flux3 import Flux3DistilledModularPipeline

        model_id = "black-forest-labs/flux-3-image-klein"
        variant = "nvfp4"  # quantized transformer for low VRAM
        dtype = torch.bfloat16

        transformer = Flux3Transformer2DModel.from_single_file(
            f"https://huggingface.co/{model_id}/blob/main/variants/{variant}/model.safetensors",
            config=model_id,
            subfolder="transformer",
            quantization_config=BFLQuantizationConfig(compute_dtype=dtype),
            dtype=dtype,
        )

        from diffusers import ComponentsManager

        manager = ComponentsManager()
        if torch.cuda.is_available() and self.config.force_device != "cpu":
            manager.enable_auto_cpu_offload(device="cuda")

        pipe = Flux3DistilledModularPipeline.from_pretrained(model_id, components_manager=manager)
        pipe.load_components(dtype={"vae": torch.float32, "default": dtype})
        pipe.update_components(transformer=transformer)
        # Disable the prompt upsampler to save VRAM (Qwen3-VL 4B).
        try:
            pipe.blocks.sub_blocks.pop("prompt_upsampler", None)
        except Exception:
            pass
        self._pipe = pipe
        return pipe

    def generate(self, request: ImageGenRequest, verbose: bool = False) -> Image.Image:
        import torch

        pipe = self._load_pipe()
        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)
        gen = torch.Generator(device="cpu").manual_seed(seed)

        kwargs: dict[str, Any] = {
            "prompt": request.prompt,
            "height": request.height,
            "width": request.width,
            "num_inference_steps": request.num_inference_steps,
            "generator": gen,
            "output": "images",
        }
        if request.reference_images:
            kwargs["image"] = (
                request.reference_images[0]
                if len(request.reference_images) == 1
                else request.reference_images
            )
        result = pipe(**kwargs)
        images = result if not hasattr(result, "images") else result.images
        if isinstance(images, (list, tuple)):
            return images[0]
        return images

    def supports_img2img(self) -> bool:
        return True

    def supports_reference_image(self) -> bool:
        return True

    def supports_seeds(self) -> bool:
        return True

    def get_default_size(self) -> tuple[int, int]:
        return (1024, 1024)

    def get_default_steps(self) -> int:
        return 16

    def get_default_guidance_scale(self) -> float:
        return 1.0

    def validate_model_path(self) -> bool:
        if not self.config.model_path:
            return True
        return super().validate_model_path(self.config.model_path)
