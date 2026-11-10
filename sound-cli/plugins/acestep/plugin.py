from __future__ import annotations

import sys
from typing import Any

import torch

from plugins.base import MusicGenPlugin

DEFAULT_MODEL = "ACE-Step/acestep-v15-xl-turbo-diffusers"
INSTRUMENTAL = "[Instrumental]"

QUANT_BACKENDS = {"nf4": "bitsandbytes_4bit", "int8": "bitsandbytes_8bit"}
_OFF_VALUES = {"false", "none", "off", "no", "0"}


def _section(config: dict) -> dict:
    return config.get("acestep", {}) or {}


def resolve_quantization(config: dict) -> str | None:
    """Resolve ``acestep.quantization`` to ``nf4``/``int8``/None.

    ``auto`` picks ``nf4`` when bitsandbytes can be imported (the only way a
    5B transformer fits an 8 GB card) and ``none`` otherwise.
    """
    value = str(_section(config).get("quantization", "auto")).strip().lower()
    if value in _OFF_VALUES:
        return None
    if value == "auto":
        try:
            import bitsandbytes  # noqa: F401
        except ImportError:
            return None
        return "nf4"
    if value not in QUANT_BACKENDS:
        raise ValueError(
            f"acestep: unknown quantization '{value}' (use auto, none, nf4 or int8)"
        )
    return value


def resolve_offload(config: dict, quantized: bool) -> str | None:
    """Resolve ``acestep.cpu_offload`` to ``model``/``sequential``/None.

    ``auto`` skips offloading when the model is quantized (it already fits),
    otherwise uses layer-level sequential offload below 16 GB of VRAM and
    whole-model offload above it.
    """
    value = str(_section(config).get("cpu_offload", "auto")).strip().lower()
    if value in _OFF_VALUES:
        return None
    if value in {"model", "sequential"}:
        return value
    if value != "auto":
        raise ValueError(
            f"acestep: unknown cpu_offload '{value}' "
            "(use auto, false, model or sequential)"
        )

    if quantized:
        return None
    if torch.cuda.is_available():
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        if total_gb < 16:
            return "sequential"
    return "model"



def build_acestep_kwargs(
    config: dict,
    *,
    prompt: str,
    duration: float | None = None,
    lyrics: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Map config + CLI values to ``AceStepPipeline.__call__`` kwargs.

    Kept free of diffusers imports so it is unit-testable without the model
    or the optional dependency installed.

    ``duration`` and ``seed`` from the CLI win over config values. An empty
    or missing ``lyrics`` falls back to the config default, then to
    ``[Instrumental]`` — the pipeline has no language-model planner, so
    without lyrics the DiT would still try to sing.
    """
    section = _section(config)
    kwargs: dict[str, Any] = dict(section.get("extra") or {})

    actual_lyrics = lyrics if lyrics else section.get("lyrics") or INSTRUMENTAL
    actual_duration = duration if duration else section.get("duration", 30.0)

    kwargs["prompt"] = prompt
    kwargs["lyrics"] = actual_lyrics
    kwargs["audio_duration"] = float(actual_duration or 30.0)
    kwargs["vocal_language"] = section.get("vocal_language", "en")

    for key in ("num_inference_steps", "guidance_scale", "shift"):
        value = section.get(key)
        if value is not None:
            kwargs[key] = value

    actual_seed = seed if seed is not None else section.get("seed")
    if actual_seed is not None:
        kwargs["seed"] = int(actual_seed)

    return kwargs


class AcestepPlugin(MusicGenPlugin):
    """ACE-Step 1.5 music generation via the diffusers ``AceStepPipeline``.

    Runs in-process: no server, no separate binary. The pipeline wraps the
    DiT half of ACE-Step 1.5 (text encoder + condition encoder + DiT + VAE),
    so lyrics are required for vocal tracks; instrumentals use
    ``[Instrumental]``.
    """

    name = "acestep"

    def __init__(self, config: dict):
        self.config = config
        self._pipe = None

    @staticmethod
    def _log(verbose: bool, message: str) -> None:
        if verbose:
            print(f"acestep: {message}", file=sys.stderr, flush=True)

    def _load_pipeline(self, verbose: bool = False):
        if self._pipe is not None:
            return self._pipe

        try:
            from diffusers import AceStepPipeline
        except ImportError as exc:
            raise RuntimeError(
                "acestep: the diffusers AceStepPipeline is required. "
                "Install with: pip install 'sound-agent[acestep]' "
                "(or: pip install git+https://github.com/huggingface/diffusers.git)"
            ) from exc

        section = _section(self.config)
        model_id = section.get("model", DEFAULT_MODEL)
        dtype_name = str(section.get("dtype", "bfloat16"))
        dtype = getattr(torch, dtype_name, None)
        if not isinstance(dtype, torch.dtype):
            raise ValueError(
                f"acestep: unknown dtype '{dtype_name}' "
                "(use float32, float16 or bfloat16)"
            )

        device = str(section.get("device", "cuda"))
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                "acestep: device is 'cuda' but no CUDA device is available. "
                "Set acestep.device to 'cpu'."
            )

        quantization = resolve_quantization(self.config)
        offload = resolve_offload(self.config, quantized=quantization is not None)
        if offload and quantization:
            raise ValueError(
                "acestep: quantization and cpu_offload cannot be combined. "
                "Keep cpu_offload: auto or set it to false."
            )

        load_kwargs: dict[str, Any] = {"dtype": dtype}
        if quantization:
            from diffusers import PipelineQuantizationConfig

            quant_kwargs: dict[str, Any] = {
                "load_in_4bit": quantization == "nf4",
                "load_in_8bit": quantization == "int8",
                "bnb_4bit_compute_dtype": dtype,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_use_double_quant": True,
            }
            load_kwargs["quantization_config"] = PipelineQuantizationConfig(
                quant_backend=QUANT_BACKENDS[quantization],
                quant_kwargs=quant_kwargs,
                components_to_quantize=["transformer"],
            )
            load_kwargs["device_map"] = device

        self._log(
            verbose,
            f"loading {model_id} ({dtype_name}, "
            f"quantization={quantization or 'none'}, "
            f"offload={offload or 'none'})",
        )
        pipe = AceStepPipeline.from_pretrained(model_id, **load_kwargs)

        if offload:
            try:
                if offload == "sequential":
                    pipe.enable_sequential_cpu_offload()
                else:
                    pipe.enable_model_cpu_offload()
            except ImportError as exc:
                raise RuntimeError(
                    "acestep: cpu_offload needs accelerate. "
                    "Install with: pip install 'sound-agent[acestep]'"
                ) from exc
            self._log(verbose, f"{offload} CPU offload enabled")
        elif not quantization:
            pipe = pipe.to(device)
            self._log(verbose, f"pipeline moved to {device}")

        if section.get("vae_tiling", True):
            pipe.vae.enable_tiling()

        attention_backend = section.get("attention_backend")
        if attention_backend:
            pipe.transformer.set_attention_backend(attention_backend)
            pipe.condition_encoder.set_attention_backend(attention_backend)
            self._log(verbose, f"attention backend: {attention_backend}")

        self._pipe = pipe
        return pipe

    def generate(
        self,
        prompt: str,
        duration: float,
        lyrics: str | None = None,
        seed: int | None = None,
        verbose: bool = False,
        **kwargs: Any,
    ) -> tuple[torch.Tensor, int]:
        pipe = self._load_pipeline(verbose)

        params = build_acestep_kwargs(
            self.config,
            prompt=prompt,
            duration=duration,
            lyrics=lyrics,
            seed=seed,
        )
        actual_seed = params.pop("seed", None)
        if actual_seed is not None:
            device = str(_section(self.config).get("device", "cuda"))
            params["generator"] = torch.Generator(device=device).manual_seed(
                int(actual_seed)
            )

        params.update(kwargs)

        label = params.get("lyrics", INSTRUMENTAL).splitlines()[0]
        self._log(
            verbose,
            f"generating {params['audio_duration']}s, "
            f"lyrics={label!r}, seed={actual_seed}",
        )

        with torch.inference_mode():
            output = pipe(**params)

        audios = getattr(output, "audios", None)
        if audios is None:
            audios = output[0]
        audio = audios[0]

        # diffusers returns (channels, frames); soundfile wants (frames, channels).
        if audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
            audio = audio.transpose(0, 1)

        return audio.detach().to("cpu", torch.float32), int(pipe.sample_rate)
