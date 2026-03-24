from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.core.registry import build_plugins
from core.config import load_image_config
from core.engine import ImageGenEngine
from core.models import ImageGenRequest


class GenerateRequest(BaseModel):
    """Request body for image generation endpoint."""

    prompt: str = Field(..., description="Text prompt for image generation")
    width: int | None = Field(None, description="Image width")
    height: int | None = Field(None, description="Image height")
    guidance_scale: float | None = Field(None, description="Guidance scale")
    num_inference_steps: int | None = Field(
        None, description="Number of inference steps"
    )
    seed: int | None = Field(None, description="Random seed for reproducibility")
    init_image_base64: str | None = Field(None, description="Base64-encoded init image")
    strength: float | None = Field(None, description="Strength for img2img (0.0-1.0)")
    output_format: str | None = Field(
        None, description="Output format (PNG, JPEG, WEBP)"
    )
    engine: str | None = Field(None, description="Engine to use")


class GenerateResponse(BaseModel):
    """Response from image generation endpoint."""

    path: str
    seed: int
    width: int
    height: int
    engine: str
    prompt: str
    output_format: str
    generation_time: float | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    engines: list[str]


def create_app(tool_root: Path) -> FastAPI:
    """Create and configure the FastAPI application."""
    config = load_image_config()

    plugin_manifests = build_plugins(config, tool_root=tool_root)
    plugins = {}
    for name, manifest in plugin_manifests.items():
        engine_config = config.get_engine_config(name)
        plugins[name] = manifest.engine_class(engine_config)

    engine = ImageGenEngine(plugins, config)

    app = FastAPI(
        title="image-agent API",
        description="AI image generation API with FLUX.2 support",
        version="0.1.0",
    )

    @app.get("/health", response_model=HealthResponse)
    def health():
        """Health check endpoint."""
        return HealthResponse(
            status="ok",
            engines=list(plugins.keys()),
        )

    @app.post("/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest):
        """Generate an image from a text prompt."""
        init_image = None
        if req.init_image_base64:
            import base64
            from io import BytesIO
            from PIL import Image

            try:
                image_data = base64.b64decode(req.init_image_base64)
                init_image = Image.open(BytesIO(image_data)).convert("RGB")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid init image: {e}")

        request = ImageGenRequest(
            prompt=req.prompt,
            width=req.width or config.default_width,
            height=req.height or config.default_height,
            guidance_scale=req.guidance_scale
            if req.guidance_scale is not None
            else config.default_guidance_scale,
            num_inference_steps=req.num_inference_steps
            if req.num_inference_steps is not None
            else config.default_num_inference_steps,
            seed=req.seed,
            init_image=init_image,
            strength=req.strength,
            output_format=req.output_format or config.default_output_format,
            engine=req.engine,
        )

        try:
            result = engine.generate(request)
            return GenerateResponse(
                path=result.path,
                seed=result.seed,
                width=result.width,
                height=result.height,
                engine=result.engine,
                prompt=result.prompt,
                output_format=result.output_format,
                generation_time=result.generation_time,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/engines")
    def list_engines():
        """List available image generation engines."""
        return {
            "engines": list(plugins.keys()),
            "default": config.default_engine,
        }

    @app.get("/engines/{engine_name}/validate")
    def validate_engine(engine_name: str):
        """Validate an engine's configuration."""
        if engine_name not in plugins:
            raise HTTPException(
                status_code=404, detail=f"Unknown engine: {engine_name}"
            )

        engine_config = config.get_engine_config(engine_name)
        is_valid = plugins[engine_name].validate_model_path(engine_config.model_path)

        return {
            "engine": engine_name,
            "valid": is_valid,
            "model_path": engine_config.model_path,
        }

    @app.get("/config")
    def get_config():
        """Get current configuration (non-sensitive parts only)."""
        return {
            "default_engine": config.default_engine,
            "default_width": config.default_width,
            "default_height": config.default_height,
            "default_guidance_scale": config.default_guidance_scale,
            "default_num_inference_steps": config.default_num_inference_steps,
            "default_output_format": config.default_output_format,
            "output_dir": config.output_dir,
            "available_sizes": [s.to_dict() for s in config.available_sizes],
            "available_formats": config.available_formats,
            "engines": {
                name: {"model_path": cfg.model_path}
                for name, cfg in config.engines.items()
            },
        }

    return app


def run_server(host: str, port: int, tool_root: Path) -> None:
    """Run the API server."""
    import uvicorn

    app = create_app(tool_root)
    uvicorn.run(app, host=host, port=port)
