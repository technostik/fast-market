from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import soundfile as sf
import torch

from common.core.paths import get_tool_cache_dir
from plugins.base import TTSPlugin

REFERENCE_TEXT = "This is a reference voice sample for voice cloning."
REF_VOICES_SUBDIR = "ref_voices"


class Qwen3TTSPlugin(TTSPlugin):
    """TTS engine using Qwen3-TTS with dual-model architecture.

    Two models work together:
      1. VoiceDesign model (``voice_design_model``) — creates a stable reference
         audio from a natural-language voice description.
      2. Base model (``base_model``) — clones that reference for every TTS
         request, guaranteeing the same voice every time.

    When ``clone`` is set in the config, the reference is produced directly by
    the Base model's ``generate_voice_clone`` instead of the VoiceDesign model.
    """

    name = "qwen3"

    def __init__(self, config: dict):
        self.config = config
        self._voice_design_model = None
        self._base_model = None

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def _get_voice_design_model(self):
        if self._voice_design_model is not None:
            return self._voice_design_model

        from qwen_tts import Qwen3TTSModel

        model_id = self.config.get(
            "voice_design_model",
            "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        )
        self._voice_design_model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map="auto",
            dtype=torch.bfloat16,
        )
        return self._voice_design_model

    def _get_base_model(self):
        if self._base_model is not None:
            return self._base_model

        from qwen_tts import Qwen3TTSModel

        model_id = self.config.get(
            "base_model",
            "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        )
        self._base_model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map="auto",
            dtype=torch.bfloat16,
        )
        return self._base_model

    # ------------------------------------------------------------------
    # Stable voice identity  (hash-based reference detection)
    # ------------------------------------------------------------------

    @staticmethod
    def _voice_key(voice: str, clone: str | None, ref_text: str | None) -> str:
        if clone:
            return f"{voice}||{clone}||{ref_text or ''}"
        return voice

    @staticmethod
    def _voice_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _ref_voice_dir(self) -> Path:
        d = get_tool_cache_dir("sound") / REF_VOICES_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ref_voice_path(self, voice_hash: str) -> Path:
        return self._ref_voice_dir() / f"{voice_hash}.wav"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log(msg: str) -> None:
        print(f"[qwen3] {msg}", file=sys.stderr)

    @staticmethod
    def _to_cpu_tensor(audio: Any) -> torch.Tensor:
        if isinstance(audio, torch.Tensor):
            return audio.cpu()
        return torch.from_numpy(audio)

    @staticmethod
    def _save_wav(path: Path, audio: torch.Tensor, sr: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), audio.numpy(), sr)

    # ------------------------------------------------------------------
    # Create a reference voice once and cache it
    # ------------------------------------------------------------------

    def _ensure_reference(
        self, voice: str, clone: str | None, ref_text: str | None, language: str
    ) -> Path:
        key = self._voice_key(voice, clone, ref_text)
        vhash = self._voice_hash(key)
        ref_path = self._ref_voice_path(vhash)

        if ref_path.exists():
            self._log(f"Using cached reference voice ({vhash}).")
            return ref_path

        self._log(f"Generating new reference voice ({vhash})...")

        if clone:
            model = self._get_base_model()
            wavs, sr = model.generate_voice_clone(
                text=REFERENCE_TEXT,
                language=language,
                ref_audio=clone,
                ref_text=ref_text,
                x_vector_only_mode=(ref_text is None),
            )
        else:
            model = self._get_voice_design_model()
            wavs, sr = model.generate_voice_design(
                text=REFERENCE_TEXT,
                language=language,
                instruct=voice,
                do_sample=False,
            )

        audio = self._to_cpu_tensor(wavs[0])
        self._save_wav(ref_path, audio, sr)
        return ref_path

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        language = kwargs.get("language", self.config.get("language", "English"))
        clone = kwargs.get("clone") or self.config.get("clone")
        ref_text = kwargs.get("ref_text") or self.config.get("ref_text")

        ref_path = self._ensure_reference(voice, clone, ref_text, language)

        model = self._get_base_model()
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=str(ref_path),
            ref_text=REFERENCE_TEXT,
        )

        audio = self._to_cpu_tensor(wavs[0])
        return audio, sr
