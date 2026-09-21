from __future__ import annotations

import os
import random
import sys
import time
import warnings
from typing import Any, TYPE_CHECKING

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin

if TYPE_CHECKING:
    from diffusers import QwenImage21Pipeline

#: Default HuggingFace Hub repo for the Qwen-Image-2.1 weights.
DEFAULT_MODEL_ID = "Qwen/Qwen-Image-2.1"


def _log(message: str) -> None:
    """Print a progress message to stderr (always visible, JSON-safe)."""
    print(f"qwen21: {message}", file=sys.stderr, flush=True)


def _cpu_mem_bytes() -> int | None:
    """Total system RAM in bytes (psutil, else /proc/meminfo, else None)."""
    try:
        import psutil

        return psutil.virtual_memory().total
    except ImportError:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


class Qwen21EnginePlugin(ImageEnginePlugin):
    """Qwen-Image-2.1 image generation engine (text-to-image + editing)."""

    name = "qwen21"

    def __init__(self, config: EngineConfig | dict[str, Any]):
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config
        self._pipeline: "QwenImage21Pipeline | None" = None
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

    def _load_pipeline(self, cache: bool = True) -> "QwenImage21Pipeline":
        """Load the Qwen-Image-2.1 pipeline."""
        if cache and self._pipeline is not None:
            _log("reusing cached pipeline")
            return self._pipeline

        quantization = (self.config.quantization or "none").lower()
        if quantization not in ("none", "int8", "int4"):
            raise ValueError(
                f"qwen21: unsupported quantization={self.config.quantization!r}. "
                "Valid options: null (full precision), 'int8' (bnb 8-bit on "
                "CUDA, quanto on CPU), 'int4' (bnb NF4, smallest)."
            )

        import torch

        try:
            from diffusers import QwenImage21Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "qwen21: QwenImage21Pipeline not found in installed diffusers "
                "(absent from PyPI releases up to 0.40). Install pre-release "
                "support with: "
                "pip install git+https://github.com/huggingface/diffusers "
                "and transformers>=5.17."
            ) from exc

        torch_dtype = torch.bfloat16
        if self.config.torch_dtype == "float16":
            torch_dtype = torch.float16
        elif self.config.torch_dtype == "float32":
            torch_dtype = torch.float32

        quantization_config = None
        device = self._get_device()
        split_bnb = False
        if quantization in ("int8", "int4"):
            # bitsandbytes on CUDA (layer-wise dispatchable), quanto on CPU
            # (plain load only).
            # NOTE: quanto must never meet offload hooks or device maps —
            # rebuilding its tensors from the meta device fails. And the
            # pipeline-level device map only places whole components, so a
            # 7GB transformer never fits a small GPU that way — bnb
            # components are dispatched layer-wise individually instead.
            backend = "bnb" if device == "cuda" or quantization == "int4" else "quanto"
            if backend == "bnb" and device == "cuda":
                split_bnb = True
            else:
                quantization_config = self._build_quant_config(
                    quantization, backend
                )

        model_id = self.config.model_path or DEFAULT_MODEL_ID
        _log(
            f"loading pipeline from {model_id} "
            f"(dtype={self.config.torch_dtype}, "
            f"quantization={quantization}, "
            f"local_files_only={self.config.local_files_only}) — "
            "first run downloads ~14GB, this takes a while..."
        )
        started = time.time()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # torch_dtype deprecation
            if split_bnb:
                pipe = self._load_bnb_split(
                    model_id, torch_dtype, quantization
                )
            else:
                pipe = QwenImage21Pipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch_dtype,
                    local_files_only=self.config.local_files_only,
                    quantization_config=quantization_config,
                )
        _log(f"weights loaded in {time.time() - started:.1f}s")

        _log(f"placing pipeline on {device}...")
        started = time.time()
        if split_bnb or getattr(pipe, "hf_device_map", None):
            # Components already placed (split dispatch or device map);
            # only forward-level savers (offload hooks conflict).
            if split_bnb:
                _log("components already dispatched; forward-level savers only")
            else:
                _log("pipeline already dispatched; forward-level savers only")
            self._enable_attention_slicing(pipe)
            self._enable_vae_packing(pipe)
        elif device == "cuda":
            self._apply_cuda_memory_savers(pipe)
        else:
            pipe.to(device)
        _log(f"device setup done in {time.time() - started:.1f}s")

        self._device = device
        self._pipeline = pipe
        return pipe

    def _load_bnb_split(
        self, model_id: str, torch_dtype: Any, precision: str
    ) -> "QwenImage21Pipeline":
        """Load bnb-quantized transformer + encoder on CPU, assemble pipeline.

        Plain CPU loads (no device map — bnb refuses CPU-dispatched modules
        without fp32 offload). The caller then attaches sequential offload,
        which streams submodule-by-submodule to the GPU. VAE is moved to
        CUDA explicitly (small).
        """
        from diffusers import (
            QwenImage21Pipeline,
            QwenImage21Transformer2DModel,
        )
        from transformers import Qwen3VLForConditionalGeneration

        try:
            transformer_cfg, encoder_cfg = self._build_bnb_configs(precision)
        except ImportError as exc:
            raise RuntimeError(
                "qwen21: quantization on CUDA requires bitsandbytes "
                "(pip install bitsandbytes)."
            ) from exc
        _log("loading transformer (bnb, CPU)...")
        transformer = QwenImage21Transformer2DModel.from_pretrained(
            model_id,
            subfolder="transformer",
            torch_dtype=torch_dtype,
            local_files_only=self.config.local_files_only,
            quantization_config=transformer_cfg,
        )
        self._dispatch_split(transformer, "3GiB", "transformer")
        _log("loading text encoder (bnb, CPU)...")
        text_encoder = Qwen3VLForConditionalGeneration.from_pretrained(
            model_id,
            subfolder="text_encoder",
            torch_dtype=torch_dtype,
            local_files_only=self.config.local_files_only,
            quantization_config=encoder_cfg,
        )
        self._dispatch_split(text_encoder, "1GiB", "text_encoder")
        _log("assembling pipeline from dispatched components...")
        pipe = QwenImage21Pipeline.from_pretrained(
            model_id,
            transformer=transformer,
            text_encoder=text_encoder,
            torch_dtype=torch_dtype,
            local_files_only=self.config.local_files_only,
        )
        try:
            pipe.vae.to("cuda")
            _log("VAE on CUDA")
        except Exception as exc:
            _log(f"VAE stays on CPU: {exc}")
        return pipe

    @staticmethod
    def _dispatch_split(module: Any, gpu_budget: str, name: str) -> None:
        """Spread one component across GPU/CPU with accelerate (bnb-aware).

        Plain `.to("cpu")` does not release bnb GPU storage; dispatch_model
        moves tensors properly. Hot layers stay on GPU, the rest on CPU.
        """
        from accelerate import dispatch_model, infer_auto_device_map

        max_memory: dict[Any, str] = {0: gpu_budget}
        cpu_bytes = _cpu_mem_bytes()
        if cpu_bytes:
            max_memory["cpu"] = f"{cpu_bytes / 2**30 * 0.8:.1f}GiB"
        _log(f"dispatching {name}: {max_memory}")
        device_map = infer_auto_device_map(module, max_memory=max_memory)
        dispatch_model(module, device_map=device_map)

    def _enable_attention_slicing(self, pipe: "QwenImage21Pipeline") -> None:
        if hasattr(pipe, "enable_attention_slicing"):
            try:
                pipe.enable_attention_slicing()
                _log("enabled attention slicing")
            except Exception as exc:
                _log(f"attention slicing unavailable: {exc}")

    def _enable_vae_packing(self, pipe: "QwenImage21Pipeline") -> None:
        vae = getattr(pipe, "vae", None)
        for meth in ("enable_tiling", "enable_slicing"):
            if vae is not None and hasattr(vae, meth):
                try:
                    getattr(vae, meth)()
                    _log(f"enabled VAE {meth.split('_')[1]}")
                except Exception as exc:
                    _log(f"VAE {meth} unavailable: {exc}")

    def _apply_cuda_memory_savers(self, pipe: "QwenImage21Pipeline") -> None:
        """Enable the low-VRAM stack: slicing + sequential offload + VAE tiling.

        Used for full-precision CUDA loads. Every step is guarded so version
        differences degrade to a log line instead of a crash.
        """
        import torch

        # Must be set before the first CUDA allocation in this process.
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        try:
            free, total = torch.cuda.mem_get_info()
            _log(f"VRAM: {free / 1e9:.1f}GB free / {total / 1e9:.1f}GB total")
        except Exception:
            pass

        self._enable_attention_slicing(pipe)

        # Sequential offload streams submodule-by-submodule (lowest peak
        # VRAM). NOTE: incompatible with quanto int8 weights (meta-device
        # rebuild fails) — int8 uses static dispatch instead, never this path.
        if hasattr(pipe, "enable_sequential_cpu_offload"):
            try:
                pipe.enable_sequential_cpu_offload()
                _log("enabled sequential CPU offload")
            except Exception as exc:
                _log(f"sequential offload failed, trying model offload: {exc}")
                if hasattr(pipe, "enable_model_cpu_offload"):
                    pipe.enable_model_cpu_offload()
        elif hasattr(pipe, "enable_model_cpu_offload"):
            _log("enabling model CPU offload")
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        self._enable_vae_packing(pipe)

    @staticmethod
    def _build_bnb_configs(precision: str):
        """Per-component bitsandbytes configs (transformer, text encoder)."""
        import torch

        from diffusers.quantizers.quantization_config import (
            BitsAndBytesConfig as DiffusersBitsAndBytesConfig,
        )
        from transformers import (
            BitsAndBytesConfig as TransformersBitsAndBytesConfig,
        )

        if precision == "int4":
            compute_dtype = torch.bfloat16
            return (
                DiffusersBitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=compute_dtype,
                ),
                TransformersBitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=compute_dtype,
                ),
            )
        return (
            DiffusersBitsAndBytesConfig(load_in_8bit=True),
            TransformersBitsAndBytesConfig(load_in_8bit=True),
        )

    @staticmethod
    def _build_quant_config(precision: str, backend: str):
        """Build a pipeline-level quantization config (non-split loads).

        Used when components load plainly (CPU, or full-precision CUDA):
        quanto int8 on CPU, bnb anywhere without dispatch. VAE stays full
        precision (small, quality-critical for decoding).
        """
        try:
            from diffusers.quantizers import PipelineQuantizationConfig
        except ImportError as exc:
            raise RuntimeError(
                "qwen21: quantization needs a recent diffusers "
                "(pip install git+https://github.com/huggingface/diffusers)."
            ) from exc

        if backend == "bnb":
            try:
                transformer_cfg, encoder_cfg = Qwen21EnginePlugin._build_bnb_configs(
                    precision
                )
            except ImportError as exc:
                raise RuntimeError(
                    "qwen21: quantization requires bitsandbytes "
                    "(pip install bitsandbytes)."
                ) from exc
            _log(f"quantization={precision}: transformer + text_encoder in bnb")
            return PipelineQuantizationConfig(
                quant_mapping={
                    "transformer": transformer_cfg,
                    "text_encoder": encoder_cfg,
                }
            )

        try:
            from diffusers.quantizers.quantization_config import (
                QuantoConfig as DiffusersQuantoConfig,
            )
            from transformers import QuantoConfig as TransformersQuantoConfig
        except ImportError as exc:
            raise RuntimeError(
                "qwen21: quantization on CPU requires the 'quanto' backend "
                "(pip install 'optimum-quanto>=0.2.6')."
            ) from exc

        _log("quantization=int8: transformer + text_encoder in quanto int8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # quanto deprecation
            return PipelineQuantizationConfig(
                quant_mapping={
                    "transformer": DiffusersQuantoConfig(weights_dtype="int8"),
                    "text_encoder": TransformersQuantoConfig(weights="int8"),
                }
            )

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
        """Generate an image using Qwen-Image-2.1."""
        import torch

        _log("initializing (importing torch/diffusers, may take a few seconds)...")
        pipe = self._load_pipeline(cache=self.config.model_path != "")

        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)

        generator = torch.Generator(device=self._get_device()).manual_seed(seed)

        # Qwen pipelines use true_cfg_scale (default 4.0) instead of the
        # guidance-distilled guidance_scale used by FLUX.2. Map the generic
        # request.guidance_scale onto true_cfg_scale so the shared CLI/config
        # plumbing keeps working unchanged.
        pipe_params: dict[str, Any] = {
            "prompt": request.prompt,
            "height": request.height,
            "width": request.width,
            "true_cfg_scale": request.guidance_scale,
            "num_inference_steps": request.num_inference_steps,
            "generator": generator,
        }

        if request.init_image is not None:
            pipe_params["image"] = request.init_image
            mode = "editing (init_image)"
        elif request.reference_images:
            # Qwen-Image-2.1 supports multiple reference images for editing /
            # subject consistency. The shared CLI caps references at 4, which
            # is within the model's limit of 10. Pass a single image through
            # directly, otherwise pass the list.
            refs = list(request.reference_images[:4])
            pipe_params["image"] = refs[0] if len(refs) == 1 else refs
            mode = f"editing ({len(refs)} reference image(s))"
        else:
            mode = "text-to-image"

        _log(
            f"{mode}: {request.width}x{request.height}, "
            f"{request.num_inference_steps} steps, "
            f"true_cfg_scale={request.guidance_scale}, seed={seed} — "
            "denoising started (diffusers shows a step bar below)..."
        )
        started = time.time()
        try:
            result = pipe(**pipe_params)
        except torch.OutOfMemoryError as exc:
            raise RuntimeError(
                "qwen21: CUDA out of memory during denoising. Try: "
                "lower resolution (e.g. -w 768 -h 768), "
                "quantization='int8' in engines.qwen21 config, "
                "closing other GPU apps, fewer steps (-S). "
                f"Original error: {exc}"
            ) from exc
        _log(f"denoising finished in {time.time() - started:.1f}s")
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
        return 40

    def get_default_guidance_scale(self) -> float:
        return 4.0

    def validate_model_path(
        self, model_path: str | None = None
    ) -> bool:
        """Validate the Qwen-Image-2.1 model path or Hub ID.

        Accepts an explicit path (as called by ImageGenEngine) or falls back
        to the configured model_path (as exercised by unit tests).
        Hub IDs (e.g. "Qwen/Qwen-Image-2.1") with local_files_only=False are
        considered valid without a filesystem check since weights download on
        first use.
        """
        path = model_path if model_path is not None else self.config.model_path
        if not path:
            return False
        if not self.config.local_files_only and "/" in path:
            # Looks like a HuggingFace Hub ID -> downloadable on demand.
            from pathlib import Path as _Path

            if not _Path(path).exists():
                return True
        return super().validate_model_path(path)
