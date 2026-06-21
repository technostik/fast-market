from __future__ import annotations

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


class KokoroPlugin(TTSPlugin):
    """TTS engine using Kokoro (lightweight, fast)."""

    name = "kokoro"

    def __init__(self, config: dict):
        self.config = config
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code="a")
        return self._pipeline

    def _build_voice_tensor(self, voice_str: str):
        """Build a weighted voice embedding tensor.

        Supports format like 'am_michael*0.7,am_fenrir*0.3'.
        Each voice name with *weight; weights normalized to sum 1.0.
        """
        pipeline = self._get_pipeline()
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
        import soundfile as sf
        import io

        pipeline = self._get_pipeline()
        voice_tensor = self._build_voice_tensor(voice)

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
