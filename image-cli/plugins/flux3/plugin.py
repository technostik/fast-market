from __future__ import annotations

import os
import random
import sys
from typing import Any

from PIL import Image

from core.models import EngineConfig, ImageGenRequest
from plugins.base import ImageEnginePlugin

#: Default HuggingFace Hub repo for the FLUX.3 Klein weights.
DEFAULT_MODEL_ID = "black-forest-labs/flux-3-image-klein"

#: Transformer weight formats selectable through ``engines.flux3.quantization``.
QUANTIZATIONS = ("nvfp4", "fp8r", "int8", "none")

#: Formats shipped as a pre-quantized ``variants/<name>/model.safetensors``.
SINGLE_FILE_VARIANTS = ("nvfp4", "fp8r")

#: The model accepts up to 10 references; the CLI never sends more than 4.
MAX_REFERENCES = 4


def _log(message: str) -> None:
    """Print a progress message to stderr (always visible, JSON-safe)."""
    print(f"flux3: {message}", file=sys.stderr, flush=True)


def _vram_gib() -> str:
    """Return ``"free/total GiB"`` for the current CUDA device."""
    import torch

    if not torch.cuda.is_available():
        return "no CUDA"
    free, total = torch.cuda.mem_get_info()
    return f"{free / 2**30:.2f}/{total / 2**30:.2f} GiB free"


def _release_bnb_cuda_buffers(module) -> int:
    """Drop the stale CUDA buffers bitsandbytes keeps after a move to CPU.

    ``Int8Params.to("cpu")`` replaces ``data`` but leaves ``CB``/``SCB``
    pointing at the GPU copies, which keeps ~4 GB of the text encoder alive on
    the card long after it was offloaded. Returns the number of buffers fixed.
    """
    import torch

    fixed = 0
    for parameter in module.parameters():
        for attribute in ("CB", "SCB"):
            value = getattr(parameter, attribute, None)
            if not isinstance(value, torch.Tensor) or value.device.type != "cuda":
                continue
            if attribute == "CB":
                parameter.CB = parameter.data
            else:
                parameter.SCB = value.to("cpu")
            fixed += 1
    # A forward pass also leaves the LLM.int8 kernels' cached int8 copies in
    # each layer's state; they are rebuilt on the next forward.
    for submodule in module.modules():
        state = getattr(submodule, "state", None)
        state_vars = getattr(state, "__dict__", None)
        if not isinstance(state_vars, dict):
            continue
        for attribute in ("CB", "CxB", "SB", "SCB", "A", "CAt", "subB"):
            value = state_vars.get(attribute)
            if isinstance(value, torch.Tensor) and value.device.type == "cuda":
                state_vars[attribute] = None
                fixed += 1
    return fixed


def _evict_text_encoder_block():
    """Build the pipeline block that frees the text encoder after encoding.

    Prompt encoding is the text encoder's only job, and the 8-bit Qwen3-VL
    still holds 4.6 GB while the transformer streams its weights and the VAE
    decodes. Offloading it to system RAM at that point is what makes 1024x1024
    and 1280x720 fit on an 8 GB card; the encoder is re-uploaded once per
    generation, which costs about a second.
    """
    import torch
    from diffusers.modular_pipelines import ModularPipelineBlocks

    class EvictTextEncoderBlock(ModularPipelineBlocks):
        model_name = "flux3"

        @property
        def description(self) -> str:
            return "Offloads the text encoder to system RAM once the prompt is encoded."

        @property
        def expected_components(self) -> list:
            return []

        @property
        def inputs(self) -> list:
            return []

        @property
        def intermediate_outputs(self) -> list:
            return []

        @torch.no_grad()
        def __call__(self, components, state):
            encoder = getattr(components, "text_encoder", None)
            parameter = next(encoder.parameters(), None) if encoder is not None else None
            if parameter is not None and parameter.device.type != "cpu":
                encoder.to("cpu")
                _release_bnb_cuda_buffers(encoder)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            return components, state

    return EvictTextEncoderBlock()


class Flux3EnginePlugin(ImageEnginePlugin):
    """FLUX.3 Image Klein (distilled) via diffusers ModularPipeline (local).

    The model is 5.6B parameters plus an 8.9 GB Qwen3-VL text encoder, so an
    8 GB card only fits it as a set of deliberate compromises:

    * the transformer keeps the pre-quantized ``nvfp4`` weights in system RAM
      and streams them to the GPU leaf by leaf (``leaf_level`` group offload);
    * the text encoder is loaded in 8-bit and stays on the GPU, where prompt
      encoding is fast enough and 4.4 GB is affordable;
    * the 9B prompt upsampler is dropped before any weight is downloaded.
    """

    name = "flux3"

    #: Default Hub repo for the weights.
    default_model_id = DEFAULT_MODEL_ID

    def __init__(self, config: EngineConfig | dict[str, Any]):
        explicit_path = config.get("model_path") if isinstance(config, dict) else None
        if isinstance(config, dict):
            config = EngineConfig.from_dict(config)
        self.config = config
        if not explicit_path and config.model_path in ("", EngineConfig().model_path):
            # No path configured for this engine (the block is missing from an
            # older config file and EngineConfig filled in its generic default):
            # fall back to this engine's own Hub checkpoint.
            config.model_path = self.default_model_id
            config.local_files_only = False
        self._pipe = None

    # ------------------------------------------------------------------ setup

    def _device(self) -> str:
        if self.config.force_device:
            return self.config.force_device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def _quantization(self) -> str:
        value = (self.config.quantization or "nvfp4").strip().lower()
        if value not in QUANTIZATIONS:
            raise ValueError(
                f"flux3: unknown quantization {value!r} (expected one of {', '.join(QUANTIZATIONS)})"
            )
        return value

    def _hub_kwargs(self) -> dict[str, Any]:
        return {"local_files_only": True} if self.config.local_files_only else {}

    def _check_capability(self, variant: str) -> None:
        """Warn or fail when a weight format cannot run on this GPU."""
        import torch

        if not torch.cuda.is_available():
            return
        capability = torch.cuda.get_device_capability()
        name = torch.cuda.get_device_name()
        if variant == "fp8r" and capability < (8, 9):
            raise RuntimeError(
                f"flux3: fp8r weights need an Ada or newer GPU (compute capability >= 8.9); "
                f"{name} reports {capability[0]}.{capability[1]}. Use quantization: int8 or none."
            )
        if variant == "nvfp4" and capability[0] < 10:
            _log(
                f"nvfp4 on {name} ({capability[0]}.{capability[1]}): no native FP4 kernels before Blackwell, "
                "so every linear is dequantized to bf16 at each of the 16 steps. Correct but slow; "
                "set engines.flux3.quantization to int8 (or fp8r) for speed."
            )

    def _load_pipe(self):
        if self._pipe is not None:
            return self._pipe
        # Allocate late and reuse blocks: without this the transformer's
        # per-step dequantization buffers fragment the 8 GB fast.
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

        import torch
        from diffusers.modular_pipelines.flux3 import Flux3DistilledModularPipeline

        device = self._device()
        requested = self._quantization()
        quantization = requested if device == "cuda" else "none"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        hub = self._hub_kwargs()
        model_id = self.config.model_path

        pipe = Flux3DistilledModularPipeline.from_pretrained(model_id, **hub)
        self._drop_prompt_upsampler(pipe)

        transformer = self._load_transformer(model_id, quantization, dtype, device, hub)
        pipe.update_components(transformer=transformer)

        pipe.load_components(names=["tokenizer"], dtype=dtype, **hub)
        self._load_text_encoder(pipe, device=device, dtype=dtype, hub=hub)

        # The VAE is fp32 (decode quality) and small enough to live on the GPU.
        pipe.load_components(names=["vae"], dtype=torch.float32, **hub)
        pipe.load_components(names=["image_processor"], **hub)
        vae = pipe.vae
        if vae is None:
            raise RuntimeError("flux3: the VAE failed to load")
        vae.to(device)
        for method in ("enable_tiling", "enable_slicing"):
            if hasattr(vae, method):
                try:
                    getattr(vae, method)()
                except Exception:  # pragma: no cover - VAE-specific
                    pass

        if device == "cuda" and requested != quantization:
            _log(f"no CUDA device: quantization {requested!r} replaced by {quantization!r}")

        self._pipe = pipe
        _log(f"ready (transformer {quantization}, {_vram_gib()})")
        return pipe

    def _drop_prompt_upsampler(self, pipe) -> None:
        """Remove the 9B prompt upsampler before any of its weights load.

        ``pipe.blocks`` returns a deep copy, so the documented
        ``pipe.blocks.sub_blocks.pop(...)`` has no effect; the modified copy
        must be installed back as the pipeline's blocks.
        """
        blocks = pipe.blocks
        try:
            blocks.sub_blocks.pop("prompt_upsampler")
        except KeyError:
            _log("prompt upsampler step not found; leaving the pipeline as shipped")
        else:
            _log(
                "prompt upsampler disabled (Qwen3.5-9B, ~18 GB: it cannot share 8 GB of VRAM with the model). "
                "Prompts reach the transformer as typed, which is weaker than BFL's caption expansion"
            )

        # Free the text encoder as soon as the prompt is encoded, before the
        # transformer starts streaming and the VAE decodes.
        try:
            index = list(blocks.sub_blocks.keys()).index("vae_encoder")
        except ValueError:
            pass
        else:
            blocks.sub_blocks.insert("evict_text_encoder", _evict_text_encoder_block(), index)
        pipe._blocks = blocks

    def _load_transformer(self, model_id: str, quantization: str, dtype, device: str, hub: dict):
        import torch
        from diffusers import Flux3Transformer2DModel

        if quantization in SINGLE_FILE_VARIANTS:
            self._check_capability(quantization)
            from huggingface_hub import hf_hub_download

            checkpoint = hf_hub_download(
                model_id, f"variants/{quantization}/model.safetensors", **hub
            )
            from diffusers import BFLQuantizationConfig

            transformer = Flux3Transformer2DModel.from_single_file(
                checkpoint,
                config=model_id,
                subfolder="transformer",
                quantization_config=BFLQuantizationConfig(compute_dtype=dtype),
                dtype=dtype,
                **hub,
            )
        else:
            kwargs: dict[str, Any] = {"subfolder": "transformer", "dtype": dtype, **hub}
            if quantization == "int8":
                from diffusers.quantizers.quantization_config import BitsAndBytesConfig

                kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
            transformer = Flux3Transformer2DModel.from_pretrained(model_id, **kwargs)

        if device != "cuda":
            return transformer.to(device)

        if quantization == "int8":
            # bitsandbytes already keeps the weights on the GPU in 8 bits.
            _log(f"transformer: int8 bitsandbytes ({_vram_gib()})")
            return transformer

        # Stream the whole transformer from system RAM, one leaf at a time.
        # On 8 GB this is what keeps the 11 GB bf16 / 5 GB fp4 weights usable.
        transformer.enable_group_offload(
            onload_device=torch.device(device),
            offload_device=torch.device("cpu"),
            offload_type="leaf_level",
            non_blocking=True,
        )
        _log(f"transformer: {quantization}, streamed from RAM leaf by leaf")
        return transformer

    def _load_text_encoder(self, pipe, device: str, dtype, hub: dict) -> None:
        kwargs: dict[str, Any] = {"dtype": dtype, **hub}
        quantized = False
        if device == "cuda":
            try:
                from transformers import BitsAndBytesConfig

                kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
                quantized = True
            except ImportError:  # pragma: no cover - transformers always ships it
                _log("bitsandbytes unavailable: the text encoder loads in bf16 and will not fit in 8 GB")
        pipe.load_components(names=["text_encoder"], **kwargs)
        text_encoder = pipe.text_encoder
        if text_encoder is None:
            raise RuntimeError(
                "flux3: the Qwen3-VL text encoder failed to load (see the warning above); "
                "8-bit loading needs `pip install bitsandbytes`"
            )
        text_encoder.to(device)
        mode = "int8 (bitsandbytes)" if quantized else str(dtype)
        _log(f"text encoder: {mode} on {next(text_encoder.parameters()).device}")
        if device == "cuda" and not quantized:
            _log(
                "warning: the text encoder is 8.9 GB in bf16 and does not fit on this GPU; "
                "install bitsandbytes to load it in 8-bit"
            )

    # ------------------------------------------------------------- generation

    def generate(self, request: ImageGenRequest, verbose: bool = False) -> Image.Image:
        import torch

        pipe = self._load_pipe()
        self._ensure_text_encoder_on(pipe, self._device())
        seed = request.seed
        if seed is None:
            seed = random.randint(0, 999999999)
        gen = torch.Generator(device="cpu").manual_seed(seed)

        images = self._reference_images(request)
        kwargs: dict[str, Any] = {
            "prompt": request.prompt,
            "height": request.height,
            "width": request.width,
            "num_inference_steps": request.num_inference_steps,
            "generator": gen,
            "output": "images",
        }
        if images:
            kwargs["image"] = images[0] if len(images) == 1 else images
        with torch.inference_mode():
            result = pipe(**kwargs)
        images_out = result if not hasattr(result, "images") else result.images
        if isinstance(images_out, (list, tuple)):
            return images_out[0]
        return images_out

    @staticmethod
    def _ensure_text_encoder_on(pipe, device: str) -> None:
        """Re-upload the text encoder the eviction block parked in RAM."""
        encoder = getattr(pipe, "text_encoder", None)
        parameter = next(encoder.parameters(), None) if encoder is not None else None
        if parameter is not None and parameter.device.type != device.split(":")[0]:
            encoder.to(device)

    @staticmethod
    def _reference_images(request: ImageGenRequest) -> list[Image.Image]:
        """Collect the conditioning images, ``init_image`` first.

        FLUX.3 Klein is reference-conditioned (there is no mask-based
        interface), so an init image is what this model calls a reference —
        passing it through is honest, dropping it silently is not.
        """
        if request.init_image is not None and request.reference_images:
            _log("init_image used as the first reference image (this model edits by reference)")
        images = []
        if request.init_image is not None:
            images.append(request.init_image.convert("RGB"))
        images.extend(image.convert("RGB") for image in (request.reference_images or []))
        return images[:MAX_REFERENCES]

    # ----------------------------------------------------------- capabilities

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
