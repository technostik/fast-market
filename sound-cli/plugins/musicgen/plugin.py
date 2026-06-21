from __future__ import annotations

from typing import Any

import torch

from plugins.base import MusicGenPlugin


class MusicGenModelPlugin(MusicGenPlugin):
    """Music generation using Facebook MusicGen models."""

    name = "musicgen"

    def __init__(self, config: dict):
        self.config = config
        self._model = None
        self._processor = None

    def _load_model(self):
        if self._model is None:
            from transformers import MusicgenForConditionalGeneration, AutoProcessor

            model_id = self.config.get("model", "facebook/musicgen-medium")
            self._model = MusicgenForConditionalGeneration.from_pretrained(model_id)
            self._processor = AutoProcessor.from_pretrained(model_id)
        return self._model, self._processor

    def generate(
        self, prompt: str, duration: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        model, processor = self._load_model()

        inputs = processor(text=[prompt], padding=True, return_tensors="pt")

        tokens_per_second = 50
        max_new_tokens = max(128, int(duration * tokens_per_second))

        audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)

        audio = audio_values[0, 0].cpu()
        sample_rate = model.config.audio_encoder.sampling_rate

        return audio, sample_rate
