from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from core.models import ImageGenRequest


class ImageEnginePlugin(ABC):
    """Abstract base class for image generation engines."""

    name: str

    @abstractmethod
    def generate(self, request: ImageGenRequest) -> Image.Image:
        """Generate an image from the request."""
        raise NotImplementedError

    @abstractmethod
    def supports_img2img(self) -> bool:
        """Return True if this engine supports img2img (init_image)."""
        raise NotImplementedError

    @abstractmethod
    def supports_seeds(self) -> bool:
        """Return True if this engine supports seed-based generation."""
        raise NotImplementedError

    @abstractmethod
    def get_default_size(self) -> tuple[int, int]:
        """Return default image size (width, height)."""
        raise NotImplementedError

    @abstractmethod
    def get_default_steps(self) -> int:
        """Return default number of inference steps."""
        raise NotImplementedError

    @abstractmethod
    def get_default_guidance_scale(self) -> float:
        """Return default guidance scale."""
        raise NotImplementedError

    def validate_model_path(self, model_path: str) -> bool:
        """Validate that the model path exists and is accessible."""
        from pathlib import Path

        path = Path(model_path)
        if not path.exists():
            return False
        if not any(path.iterdir()) and not path.suffix:
            return False
        return True


@dataclass
class PluginManifest:
    """
    Everything a plugin contributes beyond its ImageEnginePlugin logic.

    Fields:
        name:             Must match ImageEnginePlugin.name.
        engine_class:     The ImageEnginePlugin subclass (not an instance).
        cli_options:      {command_name: [click.Option, ...]}
                          Keys are CLI command names ("generate", ...).
                          Use "*" to inject into ALL commands.
        api_router:       Optional FastAPI APIRouter with plugin-specific endpoints.
    """

    name: str
    engine_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
