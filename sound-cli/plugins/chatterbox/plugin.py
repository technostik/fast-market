from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import soundfile as sf
import torch

from common.core.paths import get_tool_cache_dir
from plugins.base import TTSPlugin

_CHATTERBOX_SAMPLE_RATE = 24000
_REF_VOICES_SUBDIR = "ref_voices"
_CONDS_CACHE_SUBDIR = "chatterbox"
# chatterbox-tts pins torch==2.6/transformers==5.2 on py<=3.12; when the host
# environment differs, generation runs in an isolated side venv instead
# (override with the `venv_python` key of the chatterbox config section).
DEFAULT_VENV_PYTHON = "~/.venvs/fast-market-chatterbox/bin/python"
_VENV_SETUP_HINT = (
    "chatterbox-tts pins torch==2.6.0 / transformers==5.2.0: build the side venv with:\n"
    "  python -m venv --system-site-packages ~/.venvs/fast-market-chatterbox\n"
    "  ~/.venvs/fast-market-chatterbox/bin/pip install chatterbox-tts\n"
    "Or point the 'venv_python' key of the chatterbox config section at another"
    " interpreter that can import chatterbox."
)

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


def resolve_venv_python(config: dict) -> Path:
    """Python interpreter of the chatterbox side venv."""
    raw = config.get("venv_python") or DEFAULT_VENV_PYTHON
    return Path(raw).expanduser()


class ChatterboxTTSPlugin(TTSPlugin):
    """TTS engine using ResembleAI/chatterbox (multilingual).

    Uses the multilingual checkpoint so a single model serves ``fr``, ``en``
    and all other supported ``language_id``s.

    Cloning is 0-shot (like qwen's ``clone`` config key, but without a
    transcript): voice identity comes from a reference audio prompt
    (``clone`` config key or ``--clone``); ``ref_text`` is not used by
    chatterbox and is absorbed for interface compatibility. The prepared
    voice conditionals (speaker embedding + prompt tokens) are persisted in
    the sound cache and reused across runs, keyed by the reference file
    content. Without a clone the model uses its built-in default voice.

    ``exaggeration`` controls expressivity (0.0 flat - 2.0 theatrical,
    0.5 default).
    """

    name = "chatterbox"

    def __init__(self, config: dict):
        # Plugins receive the whole tool config; read this engine's section
        # (fall back to the whole dict when constructed with a bare engine dict).
        self.config = config.get(self.name) if isinstance(config.get(self.name), dict) else config
        self._model: Any = None

    @staticmethod
    def _resolve_exaggeration(kwargs: dict, config: dict) -> float:
        value = kwargs.get("exaggeration")
        if value is None:
            value = config.get("exaggeration", 0.5)
        value = float(value)
        if not 0.0 <= value <= 2.0:
            msg = f"exaggeration must be within [0.0, 2.0], got {value}"
            raise ValueError(msg)
        return value

    @staticmethod
    def _conds_cache_path(clone: str | Path) -> Path:
        disk = Path(clone).read_bytes()
        digest = hashlib.sha256(disk).hexdigest()[:16]
        return (
            get_tool_cache_dir("sound") / _REF_VOICES_SUBDIR / _CONDS_CACHE_SUBDIR
            / f"{digest}.pt"
        )

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

    def _load_or_prepare_conds(self, model: Any, clone: str | None, exaggeration: float) -> None:
        """Point ``model.conds`` at the 0-shot clone reference (cached) or leave
        the built-in default voice in place."""
        if not clone:
            return
        try:
            from chatterbox.mtl_tts import Conditionals
        except ImportError:
            from chatterbox.tts import Conditionals

        cache_path = self._conds_cache_path(clone)
        if cache_path.exists():
            self._log(f"Using cached voice conditionals ({cache_path.name}).")
            model.conds = Conditionals.load(cache_path).to(model.device)
            return

        self._log("Preparing 0-shot clone conditionals (cached for next runs)...")
        model.prepare_conditionals(str(clone), exaggeration=exaggeration)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        model.conds.save(cache_path)

    @staticmethod
    def _log(message: str) -> None:
        print(message, file=sys.stderr)

    # ------------------------------------------------------------------
    # Out-of-process generation (host env cannot import chatterbox)
    # ------------------------------------------------------------------

    def _runner_path(self) -> Path:
        return Path(__file__).resolve().parent / "runner.py"

    def _synthesize_subprocess(
        self, text: str, language: str, clone: str | None, venv_python: Path, **kwargs: Any
    ) -> tuple[torch.Tensor, int]:
        out_dir = get_tool_cache_dir("sound") / "chatterbox"
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        out_path = out_dir / f"out_{digest}_{os.getpid()}.wav"
        payload = {
            "text": text,
            "language": language,
            "clone": clone,
            "exaggeration": kwargs.get("exaggeration"),
            "ref_text": kwargs.get("ref_text"),
            "speed": kwargs.get("speed", 1.0),
            "output": str(out_path),
        }
        env = dict(os.environ)
        env.pop("_SOUND_CHATTERBOX_RUNNER", None)
        proc = subprocess.run(  # noqa: S603 — interpreter from trusted config
            [str(venv_python), str(self._runner_path())],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
        )
        if proc.returncode != 0 or not out_path.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            raise RuntimeError(
                "chatterbox side venv generation failed (see log console):\n" + "\n".join(tail)
            )
        if proc.stderr:
            self._log(proc.stderr.strip())
        audio, sr = sf.read(str(out_path), always_2d=False)
        out_path.unlink(missing_ok=True)
        return torch.from_numpy(audio).float(), int(sr)

    def synthesize(
        self, text: str, voice: str, speed: float, **kwargs
    ) -> tuple[torch.Tensor, int]:
        language = resolve_chatterbox_language(
            kwargs.pop("language", None) or self.config.get("language", "fr")
        )
        clone = kwargs.pop("clone", None) or self.config.get("clone")

        venv_python = resolve_venv_python(self.config)
        if venv_python.exists() and not os.environ.get("_SOUND_CHATTERBOX_RUNNER"):
            return self._synthesize_subprocess(
                text, language, clone, venv_python, speed=speed, **kwargs
            )

        exaggeration = self._resolve_exaggeration(kwargs, self.config)

        model = self._get_model()
        self._load_or_prepare_conds(model, clone, exaggeration)
        wav = model.generate(
            text=text,
            language_id=language,
            audio_prompt_path=None,
            exaggeration=exaggeration,
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
