from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestPluginSystem:
    """Test plugin discovery and registration."""

    def test_discover_plugins(self):
        """Test that plugins are discoverable."""
        from common.core.registry import discover_plugins
        from core.config import get_default_config

        config = get_default_config()
        tool_root = Path(__file__).resolve().parents[1]

        manifests = discover_plugins(config, tool_root=tool_root)
        assert "flux2" in manifests

    def test_flux2_plugin_manifest(self):
        """Test flux2 plugin manifest structure."""
        from plugins.flux2.register import register

        manifest = register({})
        assert manifest.name == "flux2"
        assert manifest.engine_class is not None
        assert hasattr(manifest, "cli_options")

    def test_plugin_base_class(self):
        """Test ImageEnginePlugin abstract base class."""
        from plugins.base import ImageEnginePlugin

        assert hasattr(ImageEnginePlugin, "generate")
        assert hasattr(ImageEnginePlugin, "supports_img2img")
        assert hasattr(ImageEnginePlugin, "supports_seeds")
        assert hasattr(ImageEnginePlugin, "get_default_size")
        assert hasattr(ImageEnginePlugin, "get_default_steps")
        assert hasattr(ImageEnginePlugin, "get_default_guidance_scale")


class TestFlux2Plugin:
    """Test FLUX.2 plugin implementation."""

    def test_plugin_instantiation(self):
        """Test that flux2 plugin can be instantiated."""
        from plugins.flux2.plugin import Flux2EnginePlugin
        from core.models import EngineConfig

        config = EngineConfig(model_path="/nonexistent/path")
        plugin = Flux2EnginePlugin(config)

        assert plugin.name == "flux2"
        assert plugin.supports_img2img() is True
        assert plugin.supports_seeds() is True

    def test_plugin_defaults(self):
        """Test plugin default values."""
        from plugins.flux2.plugin import Flux2EnginePlugin

        plugin = Flux2EnginePlugin({})
        width, height = plugin.get_default_size()
        assert width == 1024
        assert height == 1024
        assert plugin.get_default_steps() == 4
        assert plugin.get_default_guidance_scale() == 1.0

    def test_validate_model_path_nonexistent(self):
        """Test model path validation with nonexistent path."""
        from plugins.flux2.plugin import Flux2EnginePlugin

        plugin = Flux2EnginePlugin({"model_path": "/nonexistent/path"})
        assert plugin.validate_model_path() is False

    def test_validate_model_path_empty_string(self):
        """Test model path validation with empty string."""
        from plugins.flux2.plugin import Flux2EnginePlugin

        plugin = Flux2EnginePlugin({"model_path": ""})
        assert plugin.validate_model_path() is False
