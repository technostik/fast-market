from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def runner() -> CliRunner:
    """Return a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch config directory for testing."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def mock_config():
    """Return a minimal mock config."""
    return {
        "default_engine": "flux2",
        "engines": {
            "flux2": {
                "model_path": "./flux2-klein-4b",
                "torch_dtype": "bfloat16",
                "local_files_only": True,
            }
        },
        "default_width": 1024,
        "default_height": 1024,
        "default_guidance_scale": 1.0,
        "default_num_inference_steps": 4,
        "default_output_format": "PNG",
        "default_seed": None,
        "output_dir": ".",
        "cache_pipeline": False,
        "force_device": None,
        "available_sizes": [
            {"name": "square", "width": 1024, "height": 1024},
            {"name": "portrait", "width": 768, "height": 1024},
        ],
        "available_formats": ["PNG", "JPEG", "WEBP"],
    }
