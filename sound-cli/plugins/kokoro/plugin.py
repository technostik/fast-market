from __future__ import annotations

import sys
from typing import Any

import torch

from plugins.base import TTSPlugin


def _parse_voice_string(voice: str) -> tuple[list[str], list[float]]:
    """Parse voice string like 'am_michael*0.7,am_fenrir*0.3'.

    Returns (voice_names, weights).
    Weights are normalized to sum to 1.0.
    """
    parts = [p.strip() for p in voice.split(",")]
    names: list[str] = []
    weights: list[float] = []

    for part in parts:
        if not part:
            continue
        if "*" in part:
            name, weight_str = part.rsplit("*", 1)
            try:
                weight = float(weight_str)
            except ValueError:
                weight = 1.0
        else:
            name = part
            weight = 1.0
        names.append(name.strip())
        weights.append(weight)

    if not names:
        msg = f"Empty voice string: {voice!r}"
        raise ValueError(msg)

    total = sum(weights)
    weights = [w / total for w in weights]
    return names, weights


_KOKORO_LANG_MAP: dict[str, str] = {
    # shorthands — ISO 639-1 / BCP-47
    "en": "a",
    "en-us": "a",
    "en-gb": "b",
    "gb": "b",
    "es": "e",
    "fr": "f",
    "fr-fr": "f",
    "hi": "h",
    "it": "i",
    "pt": "p",
    "pt-br": "p",
    "ja": "j",
    "zh": "z",
    # human-readable fallbacks (backward compat)
    "american english": "a",
    "british english": "b",
    "english": "a",
    "spanish": "e",
    "french": "f",
    "hindi": "h",
    "italian": "i",
    "portuguese": "p",
    "japanese": "j",
    "mandarin chinese": "z",
    "chinese": "z",
}

_KOKORO_VALID_CODES = frozenset({"a", "b", "e", "f", "h", "i", "j", "p", "z"})


def resolve_kokoro_lang_code(language: str | None) -> str:
    """Map a language value to a Kokoro ``lang_code``.

    Accepts ISO 639-1 shorthands (``en``, ``fr``, …), BCP-47 tags
    (``en-gb``, ``pt-br``, …), human-readable names (``"english"``),
    and the raw single-letter codes Kokoro itself uses (``a``, ``b``, …).

    Returns ``"a"`` (American English) on unknown input.
    """
    if not language:
        return "a"
    key = language.strip().lower().replace("_", "-")
    if key in _KOKORO_VALID_CODES:
        return key
    return _KOKORO_LANG_MAP.get(key, "a")


class KokoroPlugin(TTSPlugin):
    """TTS engine using Kokoro (lightweight, fast)."""

    name = "kokoro"

    def __init__(self, config: dict):
        self.config = config
        self._pipelines: dict[str, Any] = {}

    def _get_pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang_code] = KPipeline(lang_code=lang_code)
        return self._pipelines[lang_code]

    def _build_voice_tensor(self, voice_str: str, pipeline):
        """Build a weighted voice embedding tensor.

        Supports format like 'am_michael*0.7,am_fenrir*0.3'.
        Each voice name with *weight; weights normalized to sum 1.0.
        """
        names, weights = _parse_voice_string(voice_str)
        if len(names) == 1:
            return pipeline.load_single_voice(names[0])
        embeddings = []
        for name, weight in zip(names, weights):
            emb = pipeline.load_single_voice(name)
            embeddings.append(emb * weight)
        return sum(embeddings[1:], embeddings[0])

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        import io

        import soundfile as sf

        language = kwargs.get("language") or self.config.get("language", "en")
        lang_code = resolve_kokoro_lang_code(language)
        pipeline = self._get_pipeline(lang_code)
        voice_tensor = self._build_voice_tensor(voice, pipeline)

        audio_chunks: list[torch.Tensor] = []
        sample_rate = 24000

        for result in pipeline(text, voice=voice_tensor, speed=speed):
            audio_chunks.append(result.audio.cpu())

        if not audio_chunks:
            audio = torch.zeros(0, dtype=torch.float32)
        else:
            audio = torch.cat(audio_chunks, dim=0)

        audio_np = audio.numpy()
        buf = io.BytesIO()
        sf.write(buf, audio_np, sample_rate, format="WAV")
        buf.seek(0)
        wav, sr = sf.read(buf)
        audio_tensor = torch.from_numpy(wav)

        return audio_tensor, sample_rate
