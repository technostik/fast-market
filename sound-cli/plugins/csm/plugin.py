from __future__ import annotations

import sys
from typing import Any

import torch

from plugins.base import TTSPlugin

_CSM_MODEL_ID = "sesame/csm-1b"
_CSM_SAMPLE_RATE = 24000

_CSM_ENGLISH_ALIASES = frozenset({"en", "en-us", "eng", "english", "american english"})


def resolve_csm_language(language: str | None) -> str:
    """Normalise a language value to CSM's only supported language.

    Raises ``ValueError`` on any explicitly non-English input: csm-1b is
    English-only, so silently falling back would produce wrong output.
    """
    if not language:
        return "en"
    key = language.strip().lower().replace("_", "-")
    if key in _CSM_ENGLISH_ALIASES:
        return "en"
    msg = (
        f"Unsupported language {language!r} for csm engine: "
        "sesame/csm-1b is English-only."
    )
    raise ValueError(msg)


def resolve_csm_exaggeration(value: float | None) -> float:
    """Normalise an ``exaggeration`` (expressivity) value.

    Contained to [0.0, 2.0]; mapped to CSM sampling temperature afterwards.
    """
    if value is None:
        return 0.5
    value = float(value)
    if not 0.0 <= value <= 2.0:
        msg = f"exaggeration must be within [0.0, 2.0], got {value}"
        raise ValueError(msg)
    return value


def csm_temperature_from_exaggeration(exaggeration: float) -> float:
    """Map ``exaggeration`` [0, 2] to CSM sampling temperature.

    0.0 (flat) -> 0.5, 0.5 (neutral, csm-1b's default behaviour) -> 0.9,
    1.0 -> 1.3, clamped to 2.0 maximum. Same scale is applied to the depth
    decoder so the audio codec stays in character.
    """
    return min(2.0, 0.5 + 0.8 * float(exaggeration))


class CsmPlugin(TTSPlugin):
    """TTS engine using Sesame csm-1b (English-only).

    Voice identity comes from the numeric ``speaker_id`` the model was
    trained with (the ``voice`` argument). Optionally a first turn of
    conversational context can be supplied with ``clone`` (reference audio
    path) and ``ref_text`` (its transcript) to steer the voice.
    """

    name = "csm"

    def __init__(self, config: dict):
        # Plugins receive the whole tool config; read this engine's section
        # (fall back to the whole dict when constructed with a bare engine dict).
        self.config = config.get(self.name) if isinstance(config.get(self.name), dict) else config
        self._model: Any = None
        self._processor: Any = None

    def _resolve_device(self) -> str:
        device = self.config.get("device", "auto")
        if device and device != "auto":
            return str(device)
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _resolve_dtype(self, device: str) -> torch.dtype | None:
        dtype_name = self.config.get("dtype", "auto")
        if dtype_name in (None, "auto"):
            return torch.bfloat16 if device == "cuda" else None
        mapping: dict[str, torch.dtype | None] = {
            "bfloat16": torch.bfloat16,
            "float32": None,
            "float16": torch.float16,
        }
        if dtype_name not in mapping:
            msg = f"Unknown csm dtype {dtype_name!r}. Expected one of: {sorted(mapping)}"
            raise ValueError(msg)
        return mapping[dtype_name]

    def _get_model(self):
        if self._model is None:
            from transformers import AutoProcessor, CsmForConditionalGeneration

            model_id = self.config.get("model", _CSM_MODEL_ID)
            device = self._resolve_device()
            dtype = self._resolve_dtype(device)

            self._log(f"Loading {model_id} on {device}...")
            load_kwargs: dict[str, Any] = {"device_map": device}
            if dtype is not None:
                load_kwargs["torch_dtype"] = dtype
            self._model = CsmForConditionalGeneration.from_pretrained(
                model_id, **load_kwargs
            )
            self._processor = AutoProcessor.from_pretrained(model_id)
        return self._model

    @staticmethod
    def _log(message: str) -> None:
        print(message, file=sys.stderr)

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        language = resolve_csm_language(
            kwargs.get("language") or self.config.get("language", "en")
        )
        clone = kwargs.get("clone") or self.config.get("clone")
        ref_text = kwargs.get("ref_text") or self.config.get("ref_text")
        exaggeration = resolve_csm_exaggeration(
            kwargs.get("exaggeration")
            if kwargs.get("exaggeration") is not None
            else self.config.get("exaggeration")
        )

        if voice:
            try:
                speaker_id = int(voice)
            except ValueError as exc:
                msg = (
                    f"Invalid csm voice {voice!r}: csm speaks with a numeric "
                    "speaker id (e.g. '0', '1')."
                )
                raise ValueError(msg) from exc
        else:
            speaker_id = int(self.config.get("voice", "0"))

        conversation: list[dict[str, Any]] = []
        if clone:
            ref_text = ref_text or "This is a reference voice sample."
            conversation.append(
                {
                    "role": str(speaker_id),
                    "content": [
                        {"type": "text", "text": ref_text},
                        {"type": "audio", "path": str(clone)},
                    ],
                }
            )
        conversation.append(
            {"role": str(speaker_id), "content": [{"type": "text", "text": text}]}
        )

        model = self._get_model()
        inputs = self._processor.apply_chat_template(
            conversation, tokenize=True, return_dict=True
        ).to(model.device)

        audio = model.generate(
            **inputs,
            output_audio=True,
            temperature=csm_temperature_from_exaggeration(exaggeration),
            depth_decoder_temperature=csm_temperature_from_exaggeration(exaggeration),
        )
        if isinstance(audio, (list, tuple)):
            audio = audio[0]
        if audio.ndim > 1:
            audio = audio.squeeze(0)
        audio = audio.float().cpu()
        # speed is accepted for interface compatibility and ignored:
        # csm-1b has no native rate control. Post-generation stalls are
        # handled by the speak command (--accelerate).
        return audio, _CSM_SAMPLE_RATE
