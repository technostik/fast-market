from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Any, TYPE_CHECKING

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin

if TYPE_CHECKING:
    import torch
    from diffusers import Flux2KleinPipeline

#: Local FLUX.2 Klein 4B checkpoint. This is the model ``flux2`` runs on GPU.
CANONICAL_KLEIN_REPO = "black-forest-labs/FLUX.2-klein-4B"


def hub_cache_dir(hf_hub: Path | None = None) -> Path:
    """Hugging Face hub cache directory (``HUGGINGFACE_HUB_CACHE`` or ``HF_HOME/hub``)."""
    if hf_hub is not None:
        return hf_hub
    override = os.environ.get("HUGGINGFACE_HUB_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    home = os.environ.get("HF_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def snapshot_dir(repo_id: str, hf_hub: Path | None = None) -> Path | None:
    """Newest cached snapshot of ``repo_id`` that contains ``model_index.json``."""
    if not repo_id or "/" not in repo_id:
        return None
    snaps = hub_cache_dir(hf_hub) / ("models--" + repo_id.replace("/", "--")) / "snapshots"
    if not snaps.is_dir():
        return None
    found = [p for p in snaps.iterdir() if (p / "model_index.json").is_file()]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def default_local_dirs() -> list[Path]:
    """Checkouts used when the configured id is not on disk."""
    return [
        Path.home() / "YouTools" / "flux2-klein-4b",
        Path("./flux2-klein-4b").expanduser(),
    ]


def resolve_flux2_weights(
    model_path: str,
    *,
    hf_hub: Path | None = None,
    extra_dirs: list[Path] | None = None,
) -> tuple[str, bool]:
    """Return ``(load_path, local_files_only)`` for the flux2 engine.

    An on-disk model directory wins. Otherwise a cached snapshot of the
    configured repo, then the local Klein 4B weights. The configured string
    is kept only when nothing local exists, so a Hub download can still run.
    """
    raw = (model_path or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_dir() and (path / "model_index.json").is_file():
            return str(path.resolve()), True
        cached = snapshot_dir(raw, hf_hub)
        if cached is not None:
            return str(cached), True
    cached = snapshot_dir(CANONICAL_KLEIN_REPO, hf_hub)
    if cached is not None:
        return str(cached), True
    for candidate in extra_dirs if extra_dirs is not None else default_local_dirs():
        if (candidate / "model_index.json").is_file():
            return str(candidate.resolve()), True
    return raw or CANONICAL_KLEIN_REPO, False


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

        load_path, force_local = resolve_flux2_weights(self.config.model_path)
        if load_path != self.config.model_path:
            print(
                f"flux2: {self.config.model_path!r} is not a local model; "
                f"using {load_path}",
                file=sys.stderr,
                flush=True,
            )
        self.config.model_path = load_path
        if force_local:
            self.config.local_files_only = True

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

    def generate(self, request: ImageGenRequest, verbose: bool = False) -> Image.Image:
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
        elif request.reference_images:
            # FLUX.2 Klein has no IP-Adapter and its __call__ accepts no
            # `strength` kwarg; approximate subject consistency by using the
            # first reference as a low-strength init_image. The subject leaks
            # into the output while the prompt drives the new scene.
            pipe_params["image"] = request.reference_images[0]

        result = pipe(**pipe_params)
        return result.images[0]

    def supports_img2img(self) -> bool:
        return True

    def supports_reference_image(self) -> bool:
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
