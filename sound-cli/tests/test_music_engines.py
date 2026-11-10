from __future__ import annotations

import importlib

import pytest
import torch

from commands.helpers import resolve_music_engine
from commands.music.register import _resolve_lyrics
from plugins.acestep.plugin import (
    DEFAULT_MODEL,
    INSTRUMENTAL,
    AcestepPlugin,
    build_acestep_kwargs,
    resolve_offload,
    resolve_quantization,
)

MUSIC_ENGINES = ["acestep", "musicgen"]


class TestResolveMusicEngine:
    def test_explicit_engine_wins(self):
        config = {"default_music_engine": "acestep"}
        assert resolve_music_engine(config, "musicgen", MUSIC_ENGINES) == "musicgen"

    def test_explicit_unknown_engine_fails_loudly(self):
        with pytest.raises(ValueError, match="Unknown music engine"):
            resolve_music_engine({}, "nope", MUSIC_ENGINES)

    def test_default_music_engine(self):
        config = {"default_music_engine": "acestep", "default_engine": "kokoro"}
        assert resolve_music_engine(config, None, MUSIC_ENGINES) == "acestep"

    def test_tts_default_is_ignored(self):
        config = {"default_engine": "kokoro"}
        assert resolve_music_engine(config, None, MUSIC_ENGINES) == "acestep"

    def test_legacy_music_default_engine_still_works(self):
        config = {"default_engine": "musicgen"}
        assert resolve_music_engine(config, None, MUSIC_ENGINES) == "musicgen"

    def test_falls_back_to_first_available_engine(self):
        assert resolve_music_engine({}, None, ["musicgen"]) == "musicgen"

    def test_no_engines_fails_loudly(self):
        with pytest.raises(ValueError, match="No music engines"):
            resolve_music_engine({}, None, [])


class TestResolveLyrics:
    def test_no_options_returns_none(self):
        assert _resolve_lyrics(None, None, False) is None

    def test_inline_lyrics(self):
        assert _resolve_lyrics("[Verse]\nhello", None, False) == "[Verse]\nhello"

    def test_lyrics_file(self, tmp_path):
        path = tmp_path / "lyrics.txt"
        path.write_text("[Verse]\nhello\n", encoding="utf-8")
        assert _resolve_lyrics(None, str(path), False) == "[Verse]\nhello"

    def test_instrumental(self):
        assert _resolve_lyrics(None, None, True) == INSTRUMENTAL

    def test_instrumental_conflicts_with_lyrics(self):
        with pytest.raises(ValueError, match="not both"):
            _resolve_lyrics("hello", None, True)

    def test_lyrics_and_file_conflict(self, tmp_path):
        path = tmp_path / "lyrics.txt"
        path.write_text("hello", encoding="utf-8")
        with pytest.raises(ValueError, match="not both"):
            _resolve_lyrics("hello", str(path), False)


class TestAcestepKwargs:
    def test_defaults_to_instrumental(self):
        kwargs = build_acestep_kwargs({}, prompt="lofi beat", duration=20.0)
        assert kwargs["prompt"] == "lofi beat"
        assert kwargs["lyrics"] == INSTRUMENTAL
        assert kwargs["audio_duration"] == 20.0
        assert kwargs["vocal_language"] == "en"

    def test_lyrics_win_over_config(self):
        config = {"acestep": {"lyrics": "[Instrumental]"}}
        kwargs = build_acestep_kwargs(
            config, prompt="pop", duration=30.0, lyrics="[Verse]\nhi"
        )
        assert kwargs["lyrics"] == "[Verse]\nhi"

    def test_config_lyrics_used_when_cli_omits(self):
        config = {"acestep": {"lyrics": "[Verse]\nconfig lyric"}}
        kwargs = build_acestep_kwargs(config, prompt="pop", duration=30.0)
        assert kwargs["lyrics"] == "[Verse]\nconfig lyric"

    def test_duration_falls_back_to_config(self):
        config = {"acestep": {"duration": 45.0, "lyrics": INSTRUMENTAL}}
        kwargs = build_acestep_kwargs(config, prompt="pop", duration=0)
        assert kwargs["audio_duration"] == 45.0

    def test_sampling_defaults_come_from_config(self):
        config = {
            "acestep": {
                "num_inference_steps": 12,
                "guidance_scale": 1.0,
                "shift": 2.5,
                "seed": 7,
            }
        }
        kwargs = build_acestep_kwargs(config, prompt="pop", duration=10.0)
        assert kwargs["num_inference_steps"] == 12
        assert kwargs["guidance_scale"] == 1.0
        assert kwargs["shift"] == 2.5
        assert kwargs["seed"] == 7

    def test_cli_seed_wins_over_config(self):
        config = {"acestep": {"seed": 7}}
        kwargs = build_acestep_kwargs(
            config, prompt="pop", duration=10.0, seed=99
        )
        assert kwargs["seed"] == 99

    def test_extra_kwargs_do_not_override_core_fields(self):
        config = {"acestep": {"extra": {"prompt": "ignored", "cfg_interval_end": 0.5}}}
        kwargs = build_acestep_kwargs(config, prompt="real prompt", duration=10.0)
        assert kwargs["prompt"] == "real prompt"
        assert kwargs["cfg_interval_end"] == 0.5


class TestAcestepResolution:
    def test_auto_quantization_picks_nf4_when_bitsandbytes_present(self):
        import importlib.util

        expected = "nf4" if importlib.util.find_spec("bitsandbytes") else None
        assert resolve_quantization({}) == expected

    def test_quantization_disabled(self):
        assert resolve_quantization({"acestep": {"quantization": "none"}}) is None

    def test_quantization_int8(self):
        assert resolve_quantization({"acestep": {"quantization": "int8"}}) == "int8"

    def test_unknown_quantization_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown quantization"):
            resolve_quantization({"acestep": {"quantization": "int4"}})

    def test_offload_skipped_when_quantized(self):
        assert resolve_offload({}, quantized=True) is None

    def test_auto_offload_is_sequential_on_small_gpu(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(
            torch.cuda, "get_device_properties", lambda _: type("P", (), {"total_memory": 8e9})()
        )
        assert resolve_offload({}, quantized=False) == "sequential"

    def test_auto_offload_is_model_on_large_gpu(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(
            torch.cuda, "get_device_properties", lambda _: type("P", (), {"total_memory": 24e9})()
        )
        assert resolve_offload({}, quantized=False) == "model"

    def test_explicit_offload_values(self):
        assert resolve_offload({"acestep": {"cpu_offload": "false"}}, True) is None
        assert resolve_offload({"acestep": {"cpu_offload": "model"}}, False) == "model"

    def test_unknown_offload_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown cpu_offload"):
            resolve_offload({"acestep": {"cpu_offload": "yes"}}, False)


class TestAcestepPlugin:
    def test_constructor_is_cheap_and_lazy(self):
        plugin = AcestepPlugin({"acestep": {"model": DEFAULT_MODEL}})
        assert plugin.name == "acestep"
        assert plugin._pipe is None

    def test_manifest_declares_music_engine(self):
        from plugins.acestep.register import register
        from plugins.base import MusicGenPlugin

        manifest = register({})
        assert manifest.name == "acestep"
        assert issubclass(manifest.engine_class, MusicGenPlugin)


class TestMusicCommandHelp:
    def test_music_help_lists_new_options(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["music", "--help"])
        assert result.exit_code == 0
        assert "--lyrics" in result.output
        assert "--lyrics-file" in result.output
        assert "--instrumental" in result.output
        assert "--seed" in result.output
        assert "acestep" in result.output
