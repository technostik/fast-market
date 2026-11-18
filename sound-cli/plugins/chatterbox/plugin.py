from __future__ import annotations

import sys
from typing import Any

import torch

from plugins.base import TTSPlugin

_CHATTERBOX_SAMPLE_RATE = 24000

# language_id values accepted by chatterbox-multilingual
# (chatterbox.mtl_tts SUPPORTED_LANGUAGES, ResembleAI/chatterbox weights).
_CHATTERBOX_LANGS = frozenset(
    {
        "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it",
        "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr",
        "zh",
    }
)

_CHATTERBOX_LANG_ALIASES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "fr-fr": "fr",
    "de": "de",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "russian": "ru",
    "portuguese": "pt",
    "pt-br": "pt",
    "chinese": "zh",
    "mandarin chinese": "zh",
    "arabic": "ar",
    "danish": "da",
    "greek": "el",
    "finnish": "fi",
    "hebrew": "he",
    "hindi": "hi",
    "malay": "ms",
    "dutch": "nl",
    "norwegian": "no",
    "polish": "pl",
    "swedish": "sv",
    "swahili": "sw",
    "turkish": "tr",
    "ukrainian": "uk",
    "vietnamese": "vi",
}


def resolve_chatterbox_language(language: str | None) -> str:
    """Normalise a language value to a chatterbox ``language_id``.

    Accepts ISO 639-1 shorthands (``fr``, ``en``, …), BCP-47 tags
    (``fr-fr``, ``pt-br``, …), human-readable names (``"French"``), and raw
    language_ids. ``fr`` (French) is the default for this engine.

    Raises ``ValueError`` on unsupported languages instead of silently
    producing mispronounced audio.
    """
    if not language:
        return "fr"
    key = language.strip().lower().replace("_", "-")
    if key in _CHATTERBOX_LANGS:
        return key
    if key in _CHATTERBOX_LANG_ALIASES:
        return _CHATTERBOX_LANG_ALIASES[key]
    msg = (
        f"Unsupported language {language!r} for chatterbox engine. "
        f"Supported language_ids: {', '.join(sorted(_CHATTERBOX_LANGS))}"
    )
    raise ValueError(msg)


class ChatterboxTTSPlugin(TTSPlugin):
    """TTS engine using ResembleAI/chatterbox (multilingual).

    Uses the multilingual checkpoint so a single model serves ``fr``, ``en``
    and all other supported ``language_id``s. Voice identity comes from a
    reference audio prompt (``clone`` / ``audio_prompt_path``); without one
    the model uses its built-in default voice. ``ref_text`` is not used by
    chatterbox (its prompt encoder does not need a transcript) and is
    absorbed for interface compatibility.
    """

    name = "chatterbox"

    def __init__(self, config: dict):
        self.config = config
        self._model: Any = None

    def _resolve_device(self) -> str:
        device = self.config.get("device", "auto")
        if device and device != "auto":
            return str(device)
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _get_model(self):
        if self._model is None:
            try:
                # chatterbox-tts >= 0.1.4: multilingual class in mtl_tts,
                # official multilingual weights resolved internally.
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            except ImportError:  # earlier releases kept it in tts.py
                from chatterbox.tts import ChatterboxMultilingualTTS

            self._log("Loading chatterbox multilingual model...")
            self._model = ChatterboxMultilingualTTS.from_pretrained(
                device=self._resolve_device(),
            )
        return self._model

    @staticmethod
    def _log(message: str) -> None:
        print(message, file=sys.stderr)

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        language = resolve_chatterbox_language(
            kwargs.get("language") or self.config.get("language", "fr")
        )
        clone = kwargs.get("clone") or self.config.get("clone")

        model = self._get_model()
        wav = model.generate(
            text=text,
            language_id=language,
            audio_prompt_path=str(clone) if clone else None,
            exaggeration=float(self.config.get("exaggeration", 0.5)),
            cfg_weight=float(self.config.get("cfg_weight", 0.5)),
            temperature=float(self.config.get("temperature", 0.8)),
        )

        # Speed is accepted for interface compatibility and ignored:
        # chatterbox has no native rate control. Post-generation time-stretch
        # is handled by the speak command (--accelerate).
        audio = torch.as_tensor(wav).float().cpu()
        if audio.ndim > 1:
            audio = audio.squeeze(0)
        return audio, int(getattr(model, "sr", _CHATTERBOX_SAMPLE_RATE))
