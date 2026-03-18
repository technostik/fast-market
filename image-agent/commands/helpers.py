from __future__ import annotations

import logging
import sys
from pathlib import Path

from common import structlog
from common.cli.helpers import out
from common.core.registry import build_plugins

from core.config import load_image_config
from core.engine import ImageGenEngine
from core.models import EngineConfig, ImageGenConfig

logger = structlog.get_logger(__name__)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


_NOISY_LOGGERS = [
    "transformers",
    "huggingface_hub",
    "torch",
    "diffusers",
    "filelock",
    "urllib3",
]


def build_engine(
    verbose: bool,
    cache_pipeline: bool | None = None,
) -> tuple[ImageGenEngine, dict[str, ImageGenConfig], ImageGenConfig]:
    """Construct the ImageGenEngine and plugins from config."""
    _configure_logging(verbose)
    config = load_image_config()

    if cache_pipeline is not None:
        config = ImageGenConfig.from_dict(
            {
                **{
                    "engines": {k: v.to_dict() for k, v in config.engines.items()},
                    "default_engine": config.default_engine,
                    "default_width": config.default_width,
                    "default_height": config.default_height,
                    "default_guidance_scale": config.default_guidance_scale,
                    "default_num_inference_steps": config.default_num_inference_steps,
                    "default_output_format": config.default_output_format,
                    "default_seed": config.default_seed,
                    "output_dir": config.output_dir,
                    "force_device": config.force_device,
                    "available_sizes": [s.to_dict() for s in config.available_sizes],
                    "available_formats": config.available_formats,
                },
                "cache_pipeline": cache_pipeline,
            }
        )

    plugin_manifests = build_plugins(config, tool_root=_TOOL_ROOT)
    plugins = {}
    for name, manifest in plugin_manifests.items():
        engine_config = config.get_engine_config(name)
        plugins[name] = manifest.engine_class(engine_config)

    engine = ImageGenEngine(plugins, config)
    return engine, plugins, config


def _configure_logging(verbose: bool) -> None:
    """Configure logging based on verbosity level."""
    level = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
        force=True,
    )
    logging.root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)

    try:
        from common import structlog as _structlog

        _structlog.configure(
            wrapper_class=_structlog.make_filtering_bound_logger(level),
            logger_factory=_structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    except Exception:
        pass

    if not verbose:
        try:
            import transformers

            transformers.logging.set_verbosity_error()
        except (ImportError, AttributeError):
            pass
        try:
            import diffusers

            diffusers.logging.set_verbosity_error()
        except (ImportError, AttributeError):
            pass
