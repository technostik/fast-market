from __future__ import annotations

from pathlib import Path

import pytest

from core.models import (
    EngineConfig,
    ImageGenConfig,
    ImageGenRequest,
    ImageGenResult,
    ImageSize,
)


class TestImageSize:
    def test_create(self):
        size = ImageSize(name="square", width=1024, height=1024)
        assert size.name == "square"
        assert size.width == 1024
        assert size.height == 1024

    def test_to_dict(self):
        size = ImageSize(name="square", width=1024, height=1024)
        result = size.to_dict()
        assert result == {"name": "square", "width": 1024, "height": 1024}


class TestEngineConfig:
    def test_defaults(self):
        config = EngineConfig()
        assert config.model_path == "./flux2-klein-4b"
        assert config.torch_dtype == "bfloat16"
        assert config.local_files_only is True

    def test_from_dict(self):
        data = {
            "model_path": "/custom/path",
            "torch_dtype": "float16",
            "local_files_only": False,
        }
        config = EngineConfig.from_dict(data)
        assert config.model_path == "/custom/path"
        assert config.torch_dtype == "float16"
        assert config.local_files_only is False

    def test_from_dict_empty(self):
        config = EngineConfig.from_dict({})
        assert config.model_path == "./flux2-klein-4b"

    def test_from_dict_invalid(self):
        config = EngineConfig.from_dict("invalid")
        assert config.model_path == "./flux2-klein-4b"

    def test_to_dict(self):
        config = EngineConfig(
            model_path="/path", torch_dtype="float16", local_files_only=False
        )
        result = config.to_dict()
        assert result["model_path"] == "/path"
        assert result["torch_dtype"] == "float16"
        assert result["local_files_only"] is False


class TestImageGenRequest:
    def test_defaults(self):
        request = ImageGenRequest(prompt="a cat")
        assert request.prompt == "a cat"
        assert request.width == 1024
        assert request.height == 1024
        assert request.guidance_scale == 1.0
        assert request.num_inference_steps == 4
        assert request.seed is None
        assert request.init_image is None
        assert request.strength is None
        assert request.output_format == "PNG"
        assert request.engine is None

    def test_to_dict(self):
        request = ImageGenRequest(prompt="a dog", width=512, height=512, seed=42)
        result = request.to_dict()
        assert result["prompt"] == "a dog"
        assert result["width"] == 512
        assert result["height"] == 512
        assert result["seed"] == 42
        assert result["init_image"] is False


class TestImageGenResult:
    def test_creation(self):
        result = ImageGenResult(
            path="/output/image.png",
            seed=123,
            width=1024,
            height=1024,
            engine="flux2",
            prompt="a cat",
            output_format="PNG",
            generation_time=1.5,
        )
        assert result.path == "/output/image.png"
        assert result.seed == 123
        assert result.generation_time == 1.5

    def test_to_dict(self):
        result = ImageGenResult(
            path="/output/image.png",
            seed=123,
            width=1024,
            height=1024,
            engine="flux2",
            prompt="a cat",
            output_format="PNG",
        )
        data = result.to_dict()
        assert data["path"] == "/output/image.png"
        assert data["seed"] == 123
        assert data["engine"] == "flux2"


class TestImageGenConfig:
    def test_defaults(self):
        config = ImageGenConfig()
        assert config.default_engine == "flux2"
        assert config.default_width == 1024
        assert config.default_height == 1024
        assert config.cache_pipeline is True
        assert len(config.available_sizes) == 6
        assert "PNG" in config.available_formats

    def test_from_dict(self, mock_config):
        config = ImageGenConfig.from_dict(mock_config)
        assert config.default_engine == "flux2"
        assert config.default_width == 1024
        assert config.engines["flux2"].model_path == "./flux2-klein-4b"
        assert len(config.available_sizes) == 2
        assert config.available_sizes[0].name == "square"

    def test_from_dict_empty(self):
        config = ImageGenConfig.from_dict({})
        assert config.default_engine == "flux2"
        assert config.default_width == 1024

    def test_get_size(self, mock_config):
        config = ImageGenConfig.from_dict(mock_config)
        size = config.get_size("square")
        assert size is not None
        assert size.width == 1024
        assert size.height == 1024

        size = config.get_size("nonexistent")
        assert size is None

    def test_get_engine_config(self, mock_config):
        config = ImageGenConfig.from_dict(mock_config)
        engine_config = config.get_engine_config("flux2")
        assert engine_config.model_path == "./flux2-klein-4b"

        engine_config = config.get_engine_config("nonexistent")
        assert engine_config.model_path == "./flux2-klein-4b"  # Default
