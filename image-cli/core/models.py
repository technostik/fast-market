from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass(slots=True)
class TextOverlayConfig:
    """Configuration for superimposing text on a generated image."""

    enabled: bool = False
    text: str = ""
    vpos: str = "bottom"  # top / middle / bottom
    hpos: str = "center"  # left / center / right
    size: str = "fit"  # "fit" or an integer font point size like "48"
    fg: str = "blue"
    bg: str = "light green"  # "none" disables the background effect
    effect: str = "band"  # none / box / shadow / band
    style: str = "normal"  # normal / bold / italic / bold-italic
    band_size: int = 8  # band height as % of image height (band effect only)
    size_pct: float = 100  # font size multiplier vs the resolved default (100 = unchanged)
    offset_pct: int = 0  # shift text + band downward by this %% of image height

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "text": self.text,
            "vpos": self.vpos,
            "hpos": self.hpos,
            "size": self.size,
            "fg": self.fg,
            "bg": self.bg,
            "effect": self.effect,
            "style": self.style,
            "band_size": self.band_size,
            "size_pct": self.size_pct,
            "offset_pct": self.offset_pct,
        }


@dataclass(slots=True)
class OverlayConfig:
    """Stored defaults for text overlay (the `overlay:` config group)."""

    font: str = "Tomorrow"
    vpos: str = "bottom"
    hpos: str = "center"
    size: str = "fit"
    fg: str = "blue"
    bg: str = "light green"
    effect: str = "band"
    style: str = "normal"
    band_size: int = 8
    size_pct: float = 100
    offset_pct: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "font": self.font,
            "vpos": self.vpos,
            "hpos": self.hpos,
            "size": self.size,
            "fg": self.fg,
            "bg": self.bg,
            "effect": self.effect,
            "style": self.style,
            "band_size": self.band_size,
            "size_pct": self.size_pct,
            "offset_pct": self.offset_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OverlayConfig:
        if not isinstance(data, dict):
            return cls()
        return cls(
            font=data.get("font", "Tomorrow"),
            vpos=data.get("vpos", "bottom"),
            hpos=data.get("hpos", "center"),
            size=data.get("size", "fit"),
            fg=data.get("fg", "blue"),
            bg=data.get("bg", "light green"),
            effect=data.get("effect", "band"),
            style=data.get("style", "normal"),
            band_size=data.get("band_size", 8),
            size_pct=data.get("size_pct", 100),
            offset_pct=data.get("offset_pct", 0),
        )


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
    # Reference image(s) for subject/character consistency. The engine keeps the
    # subject of the reference and places it into the new scene. Supports up to 4
    # references (indexed 0..3) — referenced in the prompt as "image 0", etc.
    reference_images: list[Image.Image] | None = None
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
            "reference_images": len(self.reference_images or []),
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
    base_path: str | None = None  # the generated image *without* any overlay

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
            "base_path": self.base_path,
        }


@dataclass(slots=True)
class EngineConfig:
    """Configuration for a specific image engine."""

    model_path: str = "./flux2-klein-4b"
    torch_dtype: str = "bfloat16"
    local_files_only: bool = True
    force_device: str | None = None
    # Cloudflare Workers AI fields (used by flux2cloud plugin)
    account_id: str = ""
    api_token: str = ""
    cf_model: str = "@cf/black-forest-labs/flux-2-klein-4b"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineConfig:
        if not isinstance(data, dict):
            return cls()
        return cls(
            model_path=data.get("model_path", cls().model_path),
            torch_dtype=data.get("torch_dtype", cls().torch_dtype),
            local_files_only=data.get("local_files_only", cls().local_files_only),
            force_device=data.get("force_device", cls().force_device),
            account_id=data.get("account_id", ""),
            api_token=data.get("api_token", ""),
            cf_model=data.get("cf_model", "@cf/black-forest-labs/flux-2-klein-4b"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "torch_dtype": self.torch_dtype,
            "local_files_only": self.local_files_only,
            "force_device": self.force_device,
            "account_id": self.account_id,
            "api_token": self.api_token,
            "cf_model": self.cf_model,
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
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
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
            overlay=OverlayConfig.from_dict(data.get("overlay", {})),
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
