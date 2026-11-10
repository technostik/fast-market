from __future__ import annotations

from common.core.config import load_tool_config


def _default_config() -> dict:
    """Return the built-in sound configuration defaults."""
    return {
        "default_engine": "kokoro",
        "default_music_engine": "acestep",
        "kokoro": {
            "voice": "am_michael*0.7,am_fenrir*0.3",
            "speed": 1.0,
            "language": "en",
        },
        "qwen3": {
            "voice": "A warm, friendly male voice with a professional tone",
            "language": "en",
            "voice_design_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "base_model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "clone": None,
            "ref_text": None,
        },
        "acestep": {
            "model": "ACE-Step/acestep-v15-xl-turbo-diffusers",
            "duration": 30.0,
            "lyrics": "[Instrumental]",
            "vocal_language": "en",
            "num_inference_steps": 8,
            "guidance_scale": 1.0,
            "shift": 3.0,
            "dtype": "bfloat16",
            "device": "cuda",
            "quantization": "auto",
            "cpu_offload": "auto",
            "vae_tiling": True,
            "attention_backend": None,
        },
        "musicgen": {
            "model": "facebook/musicgen-medium",
            "duration": 5.0,
        },
        "transcribe": {
            "model": "medium",
            "language": "auto",
            "cloudflare": {
                "account_id": None,
                "api_token": None,
                "model": "@cf/openai/whisper-large-v3-turbo",
            },
        },
        "output_format": "wav",
    }


def load_sound_config(path: str | None = None) -> dict:
    """Load sound configuration with defaults."""
    raw = load_tool_config("sound", path)

    merged = _default_config()
    merged.update(raw)
    return merged


def get_default_config() -> dict:
    """Return default config dict for setup wizard."""
    return _default_config()
