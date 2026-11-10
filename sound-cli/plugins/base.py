from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class TTSPlugin(ABC):
    """Abstract base class for text-to-speech engines."""

    name: str

    @abstractmethod
    def synthesize(self, text: str, voice: str, speed: float, **kwargs) -> tuple[Any, int]:
        """Synthesize speech from text.

        Returns:
            Tuple of (audio_tensor, sample_rate).
        """
        raise NotImplementedError


class MusicGenPlugin(ABC):
    """Abstract base class for music generation engines."""

    name: str

    @abstractmethod
    def generate(self, prompt: str, duration: float, **kwargs) -> tuple[Any, int]:
        """Generate music from a text prompt.

        Engines may accept extra keyword arguments (``lyrics``, ``seed``,
        ``verbose``, …) and must ignore the ones they do not support.

        Returns:
            Tuple of (audio, sample_rate). ``audio`` is either a 1-D mono
            tensor of shape (frames,) or a 2-D tensor of shape
            (frames, channels) — the layout ``soundfile.write`` expects.
        """
        raise NotImplementedError


@dataclass
class PluginManifest:
    name: str
    engine_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
