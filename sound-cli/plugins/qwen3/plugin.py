from __future__ import annotations

from typing import Any

import torch

from plugins.base import TTSPlugin


class Qwen3TTSPlugin(TTSPlugin):
    """TTS engine using Qwen3-TTS VoiceDesign model."""

    name = "qwen3"

    def __init__(self, config: dict):
        self.config = config
        self._model = None

    def _get_model(self):
        if self._model is None:
            from qwen_tts import Qwen3TTSModel

            model_id = self.config.get(
                "model", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
            )
            self._model = Qwen3TTSModel.from_pretrained(
                model_id,
                device_map="auto",
                dtype=torch.bfloat16,
            )
        return self._model

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        model = self._get_model()
        language = kwargs.get("language", self.config.get("language", "English"))

        wavs, sr = model.generate_voice_design(
            text=text,
            language=language,
            instruct=voice,
        )

        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu()
        else:
            audio = torch.from_numpy(audio)

        return audio, sr
