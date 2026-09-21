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
        assert "qwen21" in manifests

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


class TestQwen21Plugin:
    """Test Qwen-Image-2.1 plugin implementation."""

    def test_plugin_manifest(self):
        """Test qwen21 plugin manifest structure."""
        from plugins.qwen21.register import register

        manifest = register({})
        assert manifest.name == "qwen21"
        assert manifest.engine_class is not None
        assert hasattr(manifest, "cli_options")

    def test_plugin_instantiation(self):
        """Test that qwen21 plugin can be instantiated."""
        from plugins.qwen21.plugin import Qwen21EnginePlugin
        from core.models import EngineConfig

        config = EngineConfig(
            model_path="Qwen/Qwen-Image-2.1", local_files_only=False
        )
        plugin = Qwen21EnginePlugin(config)

        assert plugin.name == "qwen21"
        assert plugin.supports_img2img() is True
        assert plugin.supports_reference_image() is True
        assert plugin.supports_seeds() is True

    def test_plugin_defaults(self):
        """Test plugin default values (repo-consistent size, model steps)."""
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({})
        width, height = plugin.get_default_size()
        assert width == 1024
        assert height == 1024
        assert plugin.get_default_steps() == 40
        assert plugin.get_default_guidance_scale() == 4.0

    def test_validate_hub_id(self):
        """Test Hub ID is valid when downloads are allowed."""
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "local_files_only": False}
        )
        assert plugin.validate_model_path() is True
        assert plugin.validate_model_path("Qwen/Qwen-Image-2.1") is True

    def test_validate_model_path_empty_string(self):
        """Test model path validation with empty string."""
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({"model_path": ""})
        assert plugin.validate_model_path() is False

    def test_generate_maps_guidance_to_true_cfg_scale(self):
        """Test generate() maps guidance_scale onto true_cfg_scale."""
        from unittest.mock import MagicMock, patch

        from PIL import Image

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "local_files_only": False}
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
                    width=1024,
                    height=1024,
                    guidance_scale=4.0,
                    num_inference_steps=40,
                    seed=42,
                )
            )

        assert result is fake_image
        _, kwargs = fake_pipe.call_args
        assert kwargs["true_cfg_scale"] == 4.0
        assert kwargs["num_inference_steps"] == 40
        assert "image" not in kwargs

    def test_generate_passes_single_reference_image(self):
        """Test a single reference image is passed through as image=."""
        from unittest.mock import MagicMock, patch

        from PIL import Image

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "local_files_only": False}
        )
        fake_image = Image.new("RGB", (64, 64))
        ref = Image.new("RGB", (32, 32))
        fake_pipe = MagicMock()
        fake_pipe.return_value = MagicMock(images=[fake_image])

        with (
            patch.object(plugin, "_load_pipeline", return_value=fake_pipe),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            plugin.generate(
                ImageGenRequest(
                    prompt="edit the subject",
                    width=1024,
                    height=1024,
                    guidance_scale=4.0,
                    num_inference_steps=40,
                    seed=7,
                    reference_images=[ref],
                )
            )

        _, kwargs = fake_pipe.call_args
        assert kwargs["image"] is ref

    def test_generate_logs_progress_to_stderr(self, capsys):
        """Test generate() emits stage-by-stage progress on stderr."""
        from unittest.mock import MagicMock, patch

        from PIL import Image

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "local_files_only": False}
        )
        fake_image = Image.new("RGB", (64, 64))
        fake_pipe = MagicMock()
        fake_pipe.return_value = MagicMock(images=[fake_image])

        with (
            patch.object(plugin, "_load_pipeline", return_value=fake_pipe),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            plugin.generate(
                ImageGenRequest(
                    prompt="a test scene",
                    width=1024,
                    height=1024,
                    guidance_scale=4.0,
                    num_inference_steps=40,
                    seed=42,
                )
            )

        captured = capsys.readouterr()
        assert "qwen21: " in captured.err
        assert "text-to-image" in captured.err
        assert "denoising started" in captured.err
        assert "denoising finished" in captured.err
        # Progress must stay off stdout (JSON output safety).
        assert "qwen21: " not in captured.out

    def test_invalid_quantization_raises(self):
        """Test unsupported quantization values fail fast (no model load)."""
        import pytest

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "quantization": "int2"}
        )
        with pytest.raises(ValueError, match="unsupported quantization"):
            plugin.generate(ImageGenRequest(prompt="x", seed=1))

    def test_default_load_has_no_quantization_config(self):
        """Test full-precision mode passes quantization_config=None."""
        import sys
        from unittest.mock import MagicMock, patch

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({"model_path": "Qwen/Qwen-Image-2.1"})
        fake_pipe_cls = MagicMock()
        fake_modules = {"diffusers": MagicMock(QwenImage21Pipeline=fake_pipe_cls)}

        with (
            patch.dict(sys.modules, fake_modules),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            plugin.generate(ImageGenRequest(prompt="x", seed=1))

        _, kwargs = fake_pipe_cls.from_pretrained.call_args
        assert kwargs["quantization_config"] is None

    def test_int8_builds_per_component_quant_mapping(self):
        """Test int8 on CPU uses quanto for transformer + text encoder."""
        import sys
        from unittest.mock import MagicMock, patch

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "quantization": "int8"}
        )
        fake_pipe_cls = MagicMock()
        fake_pipe_quant_cfg_cls = MagicMock()
        fake_diffusers_quanto_cfg_cls = MagicMock()
        fake_transformers_quanto_cfg_cls = MagicMock()
        fake_modules = {
            "diffusers": MagicMock(QwenImage21Pipeline=fake_pipe_cls),
            "diffusers.quantizers": MagicMock(
                PipelineQuantizationConfig=fake_pipe_quant_cfg_cls
            ),
            "diffusers.quantizers.quantization_config": MagicMock(
                QuantoConfig=fake_diffusers_quanto_cfg_cls
            ),
            "transformers": MagicMock(
                QuantoConfig=fake_transformers_quanto_cfg_cls
            ),
        }

        with (
            patch.dict(sys.modules, fake_modules),
            patch.object(plugin, "_get_device", return_value="cpu"),
        ):
            plugin.generate(ImageGenRequest(prompt="x", seed=1))

        fake_diffusers_quanto_cfg_cls.assert_called_once_with(weights_dtype="int8")
        fake_transformers_quanto_cfg_cls.assert_called_once_with(weights="int8")
        _, mapping_kwargs = fake_pipe_quant_cfg_cls.call_args
        assert set(mapping_kwargs["quant_mapping"]) == {
            "transformer",
            "text_encoder",
        }
        _, kwargs = fake_pipe_cls.from_pretrained.call_args
        assert kwargs["quantization_config"] is fake_pipe_quant_cfg_cls.return_value
        # CPU plain load: no static dispatch.
        assert "device_map" not in kwargs

    def test_int8_cuda_split_loads_components_with_layer_dispatch(self):
        """Test int8+CUDA split-loads bnb components and skips offload hooks."""
        import sys
        from unittest.mock import MagicMock, patch

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "quantization": "int8"}
        )
        fake_pipe = MagicMock()
        fake_pipe.hf_device_map = {"transformer": "cpu"}  # dispatched already

        with (
            patch.dict(sys.modules, {"diffusers": MagicMock()}),
            patch.object(
                plugin, "_load_bnb_split", return_value=fake_pipe
            ) as mock_split,
            patch.object(plugin, "_get_device", return_value="cuda"),
            patch("torch.Generator", return_value=MagicMock()),
            patch.object(
                plugin, "_apply_cuda_memory_savers"
            ) as mock_savers,
        ):
            plugin.generate(ImageGenRequest(prompt="x", seed=1))

        mock_split.assert_called_once()
        assert mock_split.call_args.args[2] == "int8"
        mock_savers.assert_not_called()
        fake_pipe.enable_attention_slicing.assert_called_once_with()
        fake_pipe.vae.enable_tiling.assert_called_once_with()

    def test_load_bnb_split_cpu_loads_both_components(self):
        """Test split-load dispatches bnb transformer + encoder via accelerate."""
        import sys
        from unittest.mock import MagicMock, patch

        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin(
            {"model_path": "Qwen/Qwen-Image-2.1", "quantization": "int8"}
        )
        fake_transformer_cls = MagicMock()
        fake_encoder_cls = MagicMock()
        fake_pipe_cls = MagicMock()
        fake_accelerate = MagicMock()
        fake_modules = {
            "diffusers": MagicMock(
                QwenImage21Pipeline=fake_pipe_cls,
                QwenImage21Transformer2DModel=fake_transformer_cls,
            ),
            "transformers": MagicMock(
                Qwen3VLForConditionalGeneration=fake_encoder_cls
            ),
            "accelerate": fake_accelerate,
        }

        with (
            patch.dict(sys.modules, fake_modules),
            patch.object(
                plugin,
                "_build_bnb_configs",
                return_value=(MagicMock(), MagicMock()),
            ) as mock_bnb,
        ):
            import torch

            pipe = plugin._load_bnb_split("Qwen/Qwen-Image-2.1", torch.bfloat16, "int8")

        mock_bnb.assert_called_once_with("int8")
        # Both components spread via accelerate (transformer 3GiB, encoder 1GiB).
        assert fake_accelerate.infer_auto_device_map.call_count == 2
        assert fake_accelerate.dispatch_model.call_count == 2
        assert fake_transformer_cls.from_pretrained.call_args.kwargs["subfolder"] == (
            "transformer"
        )
        # Plain CPU loads: no dispatch involved (bnb refuses CPU dispatch).
        assert "device_map" not in fake_transformer_cls.from_pretrained.call_args.kwargs
        assert fake_encoder_cls.from_pretrained.call_args.kwargs["subfolder"] == (
            "text_encoder"
        )
        assert "device_map" not in fake_encoder_cls.from_pretrained.call_args.kwargs
        assert (
            fake_encoder_cls.from_pretrained.call_args.kwargs["quantization_config"]
            is mock_bnb.return_value[1]
        )
        assert (
            fake_pipe_cls.from_pretrained.call_args.kwargs["transformer"]
            is fake_transformer_cls.from_pretrained.return_value
        )
        assert (
            fake_pipe_cls.from_pretrained.call_args.kwargs["text_encoder"]
            is fake_encoder_cls.from_pretrained.return_value
        )
        assert pipe is fake_pipe_cls.from_pretrained.return_value

    def test_int4_builds_nf4_mapping(self):
        """Test int4 configs use bnb NF4 for transformer + text encoder."""
        import sys
        from unittest.mock import MagicMock, patch

        from plugins.qwen21.plugin import Qwen21EnginePlugin

        fake_diffusers_bnb_cls = MagicMock()
        fake_transformers_bnb_cls = MagicMock()
        fake_modules = {
            "diffusers.quantizers.quantization_config": MagicMock(
                BitsAndBytesConfig=fake_diffusers_bnb_cls
            ),
            "transformers": MagicMock(
                BitsAndBytesConfig=fake_transformers_bnb_cls
            ),
        }

        with patch.dict(sys.modules, fake_modules):
            t_cfg, e_cfg = Qwen21EnginePlugin._build_bnb_configs("int4")

        assert fake_diffusers_bnb_cls.call_args.kwargs["load_in_4bit"] is True
        assert (
            fake_diffusers_bnb_cls.call_args.kwargs["bnb_4bit_quant_type"] == "nf4"
        )
        assert fake_transformers_bnb_cls.call_args.kwargs["load_in_4bit"] is True
        assert t_cfg is fake_diffusers_bnb_cls.return_value
        assert e_cfg is fake_transformers_bnb_cls.return_value

    def test_cuda_memory_savers_order(self):
        """Test low-VRAM stack: slicing, then sequential offload, then VAE tiling."""
        from unittest.mock import MagicMock, patch

        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({"model_path": "Qwen/Qwen-Image-2.1"})
        fake_pipe = MagicMock()

        with patch.object(plugin, "_get_device", return_value="cuda"):
            plugin._apply_cuda_memory_savers(fake_pipe)

        names = [c[0] for c in fake_pipe.mock_calls]
        assert names.index("enable_attention_slicing") < names.index(
            "enable_sequential_cpu_offload"
        )
        assert "vae.enable_tiling" in names
        assert "vae.enable_slicing" in names
        # Sequential offload wins; model offload must not run.
        assert "enable_model_cpu_offload" not in names

    def test_cuda_memory_savers_fallback_to_model_offload(self):
        """Test fallback to model offload when sequential is unavailable."""
        from unittest.mock import MagicMock

        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({"model_path": "Qwen/Qwen-Image-2.1"})
        fake_pipe = MagicMock(spec=["enable_model_cpu_offload", "vae"])
        fake_pipe.vae = MagicMock(spec=[])

        plugin._apply_cuda_memory_savers(fake_pipe)

        fake_pipe.enable_model_cpu_offload.assert_called_once_with()

    def test_generate_wraps_oom_with_hints(self):
        """Test CUDA OOM becomes an actionable RuntimeError."""
        import pytest
        import torch
        from unittest.mock import MagicMock, patch

        from core.models import ImageGenRequest
        from plugins.qwen21.plugin import Qwen21EnginePlugin

        plugin = Qwen21EnginePlugin({"model_path": "Qwen/Qwen-Image-2.1"})
        fake_pipe = MagicMock()
        fake_pipe.side_effect = torch.cuda.OutOfMemoryError("boom")

        with (
            patch.object(plugin, "_load_pipeline", return_value=fake_pipe),
            patch.object(plugin, "_get_device", return_value="cpu"),
            pytest.raises(RuntimeError, match="CUDA out of memory.*-w 768"),
        ):
            plugin.generate(ImageGenRequest(prompt="x", seed=1))
