from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass(slots=True)
class ImageSize:
    """Named image size preset."""

    name: str
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "width": self.width, "height": self.height}


@dataclass(slots=True)
class ImageGenRequest:
    """Request for image generation."""

    prompt: str
    width: int = 1024
    height: int = 1024
    guidance_scale: float = 1.0
    num_inference_steps: int = 4
    seed: int | None = None
    init_image: Image.Image | None = None
    strength: float | None = None
    output_format: str = "PNG"
    engine: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "guidance_scale": self.guidance_scale,
            "num_inference_steps": self.num_inference_steps,
            "seed": self.seed,
            "init_image": self.init_image is not None,
            "strength": self.strength,
            "output_format": self.output_format,
            "engine": self.engine,
        }


@dataclass(slots=True)
class ImageGenResult:
    """Result of image generation."""

    path: str
    seed: int
    width: int
    height: int
    engine: str
    prompt: str
    output_format: str
    generation_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "engine": self.engine,
            "prompt": self.prompt,
            "output_format": self.output_format,
            "generation_time": self.generation_time,
        }


@dataclass(slots=True)
class EngineConfig:
    """Configuration for a specific image engine."""

    model_path: str = "./flux2-klein-4b"
    torch_dtype: str = "bfloat16"
    local_files_only: bool = True
    force_device: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineConfig:
        if not isinstance(data, dict):
            return cls()
        return cls(
            model_path=data.get("model_path", cls().model_path),
            torch_dtype=data.get("torch_dtype", cls().torch_dtype),
            local_files_only=data.get("local_files_only", cls().local_files_only),
            force_device=data.get("force_device", cls().force_device),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "torch_dtype": self.torch_dtype,
            "local_files_only": self.local_files_only,
            "force_device": self.force_device,
        }


@dataclass(slots=True)
class ImageGenConfig:
    """Global configuration for image-agent."""

    engines: dict[str, EngineConfig] = field(default_factory=dict)
    default_engine: str = "flux2"
    default_width: int = 1024
    default_height: int = 1024
    default_guidance_scale: float = 1.0
    default_num_inference_steps: int = 4
    default_output_format: str = "PNG"
    default_seed: int | None = None
    output_dir: str = "."
    cache_pipeline: bool = True
    force_device: str | None = None
    available_sizes: list[ImageSize] = field(
        default_factory=lambda: [
            ImageSize("square", 1024, 1024),
            ImageSize("portrait", 768, 1024),
            ImageSize("landscape", 1024, 768),
            ImageSize("youtube", 1280, 720),
            ImageSize("wide", 1024, 576),
            ImageSize("tall", 576, 1024),
        ]
    )
    available_formats: list[str] = field(
        default_factory=lambda: ["PNG", "JPEG", "WEBP"]
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageGenConfig:
        if not isinstance(data, dict):
            return cls()

        engines = {}
        for name, engine_data in data.get("engines", {}).items():
            engines[name] = EngineConfig.from_dict(engine_data)

        sizes = []
        for size_data in data.get("available_sizes", []):
            if isinstance(size_data, dict):
                sizes.append(
                    ImageSize(
                        name=size_data.get("name", "custom"),
                        width=size_data.get("width", 1024),
                        height=size_data.get("height", 1024),
                    )
                )

        formats = data.get("available_formats", ["PNG", "JPEG", "WEBP"])

        return cls(
            engines=engines,
            default_engine=data.get("default_engine", "flux2"),
            default_width=data.get("default_width", 1024),
            default_height=data.get("default_height", 1024),
            default_guidance_scale=data.get("default_guidance_scale", 1.0),
            default_num_inference_steps=data.get("default_num_inference_steps", 4),
            default_output_format=data.get("default_output_format", "PNG"),
            default_seed=data.get("default_seed"),
            output_dir=data.get("output_dir", "."),
            cache_pipeline=data.get("cache_pipeline", True),
            force_device=data.get("force_device"),
            available_sizes=sizes if sizes else cls().available_sizes,
            available_formats=formats if formats else cls().available_formats,
        )

    def get_size(self, name: str) -> ImageSize | None:
        for size in self.available_sizes:
            if size.name == name:
                return size
        return None

    def get_engine_config(self, engine_name: str) -> EngineConfig:
        return self.engines.get(engine_name, EngineConfig())
