from __future__ import annotations

from pathlib import Path

from common.core.config import load_tool_config


def load_sound_config(path: str | None = None) -> dict:
    """Load sound configuration with defaults."""
    raw = load_tool_config("sound", path)

    defaults = {
        "default_engine": "kokoro",
        "kokoro": {
            "voice": "am_michael*0.7,am_fenrir*0.3",
            "speed": 1.0,
        },
        "qwen3": {
            "voice": "A warm, friendly male voice with a professional tone",
            "language": "English",
            "voice_design_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "clone": None,
            "ref_text": None,
        },
        "musicgen": {
            "model": "facebook/musicgen-medium",
            "duration": 5.0,
        },
        "output_format": "wav",
    }

    merged = dict(defaults)
    merged.update(raw)
    return merged


def get_default_config() -> dict:
    """Return default config dict for setup wizard."""
    return {
        "default_engine": "kokoro",
        "kokoro": {
            "voice": "am_michael*0.7,am_fenrir*0.3",
            "speed": 1.0,
        },
        "qwen3": {
            "voice": "A warm, friendly male voice with a professional tone",
            "language": "English",
            "voice_design_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "clone": None,
            "ref_text": None,
        },
        "musicgen": {
            "model": "facebook/musicgen-medium",
            "duration": 5.0,
        },
        "output_format": "wav",
    }
