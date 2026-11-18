"""Qwen3-TTS engine plugin.

qwen-tts 0.1.1 pins ``transformers==4.57.3``. Under transformers >= 5 the
speech tokenizer (Mimi refactor) loads with remapped/missing weights and
model code raises, so the plugin runs generation out-of-process in a
dedicated venv (default ``~/.venvs/fast-market-qwen3``, built with
``--system-site-packages`` and ``transformers==4.57.3``). The venv is
configurable via the ``venv_python`` key of the ``qwen3`` config section.

Under transformers 4.x the plugin runs in-process exactly as before.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import soundfile as sf
import torch

from common.core.paths import get_tool_cache_dir
from plugins.base import TTSPlugin

REFERENCE_TEXT = "This is a reference voice sample for voice cloning."
REF_VOICES_SUBDIR = "ref_voices"
DEFAULT_VENV_PYTHON = "~/.venvs/fast-market-qwen3/bin/python"
_VENV_SETUP_HINT = (
    "qwen-tts 0.1.1 needs transformers 4.x. Build the side venv with:\n"
    "  python -m venv --system-site-packages ~/.venvs/fast-market-qwen3\n"
    "  ~/.venvs/fast-market-qwen3/bin/pip install 'transformers==4.57.3' qwen-tts\n"
    "Or point the 'venv_python' key of the qwen3 config section at another"
    " interpreter that has transformers<5 and qwen-tts."
)

_QWEN3_LANG_MAP: dict[str, str] = {
    "en": "English",
    "english": "English",
    "zh": "Chinese",
    "chinese": "Chinese",
    "mandarin chinese": "Chinese",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "de": "German",
    "german": "German",
    "fr": "French",
    "french": "French",
    "ru": "Russian",
    "russian": "Russian",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "es": "Spanish",
    "spanish": "Spanish",
    "it": "Italian",
    "italian": "Italian",
}


def resolve_qwen3_language(language: str | None) -> str:
    """Normalise a language value to the full name Qwen3 expects.

    Accepts ISO 639-1 shorthands (``en``, ``fr``, …) and
    human-readable names (``"English"``, ``"French"``, …).
    Returns ``"English"`` on unknown input.
    """
    if not language:
        return "English"
    key = language.strip().lower().replace("_", "-").replace("-", " ")
    # Direct hit on a human-readable name
    for k, v in _QWEN3_LANG_MAP.items():
        if key == k:
            return v
        # Also match on the value itself (already a full name)
        if key == v.lower():
            return v
    return "English"


def transformers_major_version() -> int:
    """Major version of the installed transformers, 0 if unreadable."""
    try:
        import transformers

        return int(transformers.__version__.split(".")[0])
    except Exception:
        return 0


def resolve_venv_python(config: dict) -> Path:
    """Python interpreter of the transformers-4.x side venv."""
    raw = config.get("venv_python") or DEFAULT_VENV_PYTHON
    return Path(raw).expanduser()


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
    # Model lifecycle (in-process, transformers 4.x only)
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
    # Out-of-process generation (transformers >= 5)
    # ------------------------------------------------------------------

    def _runner_path(self) -> Path:
        return Path(__file__).resolve().parent / "runner.py"

    def _synthesize_subprocess(
        self,
        text: str,
        voice: str,
        speed: float,
        language: str,
        clone: str | None,
        ref_text: str | None,
        **kwargs: Any,
    ) -> tuple[torch.Tensor, int]:
        venv_python = resolve_venv_python(self.config)
        if not venv_python.exists():
            self._log(f"Side venv not found at {venv_python}.")
            raise RuntimeError(_VENV_SETUP_HINT)

        out_dir = get_tool_cache_dir("sound") / "qwen3"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"out_{self._voice_hash(text + language)}_{os.getpid()}.wav"

        payload = {
            "text": text,
            "voice": voice,
            "speed": speed,
            "language": language,
            "clone": clone,
            "ref_text": ref_text,
            "exaggeration": kwargs.get("exaggeration"),
            "output": str(out_path),
            "config": {
                "voice_design_model": self.config.get(
                    "voice_design_model", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
                ),
                "base_model": self.config.get(
                    "base_model", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
                ),
            },
        }

        proc = subprocess.run(  # noqa: S603 — interpreter from trusted config
            [str(venv_python), str(self._runner_path())],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=900,
        )
        if proc.returncode != 0 or not out_path.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError(
                "qwen3 side venv generation failed (see log console):\n"
                + "\n".join(tail)
            )

        audio, sr = sf.read(str(out_path), always_2d=False)
        out_path.unlink(missing_ok=True)
        return torch.from_numpy(audio), int(sr)

    # ------------------------------------------------------------------
    # Create a reference voice once and cache it (in-process path)
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
        language = resolve_qwen3_language(
            kwargs.pop("language", None) or self.config.get("language", "en")
        )
        clone = kwargs.pop("clone", None) or self.config.get("clone")
        ref_text = kwargs.pop("ref_text", None) or self.config.get("ref_text")

        if transformers_major_version() >= 5:
            return self._synthesize_subprocess(
                text, voice, speed, language, clone, ref_text, **kwargs
            )

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
