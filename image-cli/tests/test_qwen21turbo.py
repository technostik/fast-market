from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestQwen21TurboPlugin:
    """Test Qwen-Image-2.1-Turbo local engine."""

    def test_manifest(self):
        from plugins.qwen21turbo.register import register

        manifest = register({})
        assert manifest.name == "qwen21turbo"
        assert manifest.engine_class is not None

    def test_discovered(self):
        from common.core.registry import discover_plugins
        from core.config import get_default_config

        manifests = discover_plugins(
            get_default_config(), tool_root=Path(__file__).resolve().parents[1]
        )
        assert "qwen21turbo" in manifests

    def test_turbo_defaults(self):
        """Turbo keeps its recommended schedule: 8 steps at CFG 1.0."""
        from plugins.qwen21turbo.plugin import (
            TURBO_MODEL_ID,
            Qwen21TurboEnginePlugin,
        )

        plugin = Qwen21TurboEnginePlugin({})
        assert plugin.name == "qwen21turbo"
        assert plugin.get_default_steps() == 8
        assert plugin.get_default_guidance_scale() == 1.0
        assert plugin.default_model_id == TURBO_MODEL_ID == "Qwen/Qwen-Image-2.1-Turbo"
        assert plugin.supports_img2img() is True
        assert plugin.supports_reference_image() is True
        assert plugin.supports_seeds() is True

    def test_hub_id_valid_when_downloads_allowed(self):
        from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin

        plugin = Qwen21TurboEnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1-Turbo", "local_files_only": False}
        )
        assert plugin.validate_model_path() is True

    def test_generate_passes_kv_cache(self):
        """Turbo enables prefix KV-cache reuse on the pipeline call."""
        from unittest.mock import MagicMock, patch

        from PIL import Image

        from core.models import ImageGenRequest
        from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin

        plugin = Qwen21TurboEnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1-Turbo", "local_files_only": False}
        )
        fake_image = Image.new("RGB", (64, 64))
        fake_pipe = MagicMock()
        fake_pipe.return_value = MagicMock(images=[fake_image])

        with (
            patch.object(plugin, "_load_pipeline", return_value=fake_pipe),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            result = plugin.generate(
                ImageGenRequest(
                    prompt="a test scene",
                    width=1280,
                    height=720,
                    guidance_scale=1.0,
                    num_inference_steps=8,
                    seed=42,
                )
            )

        assert result is fake_image
        _, kwargs = fake_pipe.call_args
        assert kwargs["use_kv_cache"] is True
        assert kwargs["true_cfg_scale"] == 1.0
        assert kwargs["num_inference_steps"] == 8

    def test_generate_retries_without_kv_cache_on_old_diffusers(self):
        """Older diffusers without use_kv_cache still generate (plain retry)."""
        from unittest.mock import MagicMock, patch

        from PIL import Image

        from core.models import ImageGenRequest
        from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin

        plugin = Qwen21TurboEnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1-Turbo", "local_files_only": False}
        )
        fake_image = Image.new("RGB", (64, 64))
        fake_pipe = MagicMock(
            side_effect=[
                TypeError("pipe() got an unexpected keyword argument 'use_kv_cache'"),
                MagicMock(images=[fake_image]),
            ]
        )

        with (
            patch.object(plugin, "_load_pipeline", return_value=fake_pipe),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            result = plugin.generate(ImageGenRequest(prompt="x", seed=1))

        assert result is fake_image
        assert fake_pipe.call_count == 2
        _, retry_kwargs = fake_pipe.call_args
        assert "use_kv_cache" not in retry_kwargs

    def test_default_config_has_turbo_block(self):
        from core.config import get_default_config

        engines = get_default_config()["engines"]
        assert engines["qwen21turbo"]["model_path"] == "Qwen/Qwen-Image-2.1-Turbo"
        assert engines["qwen21turbo"]["local_files_only"] is False

    def test_missing_path_falls_back_to_hub_checkpoint(self):
        """A missing engine block (older config file) must not point at the
        generic ./flux2-klein-4b default — it resolves to the Hub ID."""
        from core.models import EngineConfig
        from plugins.qwen21.plugin import Qwen21EnginePlugin
        from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin

        turbo = Qwen21TurboEnginePlugin(EngineConfig())
        assert turbo.config.model_path == "Qwen/Qwen-Image-2.1-Turbo"
        assert turbo.config.local_files_only is False
        assert turbo.validate_model_path() is True

        turbo_dict = Qwen21TurboEnginePlugin({})
        assert turbo_dict.config.model_path == "Qwen/Qwen-Image-2.1-Turbo"

        base = Qwen21EnginePlugin(EngineConfig())
        assert base.config.model_path == "Qwen/Qwen-Image-2.1"
        assert base.config.local_files_only is False

    def test_explicit_local_path_is_preserved(self):
        from plugins.qwen21turbo.plugin import Qwen21TurboEnginePlugin

        plugin = Qwen21TurboEnginePlugin(
            {"model_path": "/my/local/turbo", "local_files_only": True}
        )
        assert plugin.config.model_path == "/my/local/turbo"
        assert plugin.config.local_files_only is True
