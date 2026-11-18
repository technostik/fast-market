from __future__ import annotations

import math
from pathlib import Path

import pytest

from core.config import get_default_config
from plugins.base import TTSPlugin
from plugins.csm.plugin import CsmPlugin, resolve_csm_language
from plugins.chatterbox.plugin import (
    ChatterboxTTSPlugin,
    resolve_chatterbox_language,
)


# --- language resolvers ---------------------------------------------------


class TestCsmLanguage:
    def test_none_defaults_to_english(self):
        assert resolve_csm_language(None) == "en"

    def test_english_aliases(self):
        for value in ("en", "en-US", "eng", "English", "american english"):
            assert resolve_csm_language(value) == "en"

    def test_non_english_fails_loudly(self):
        with pytest.raises(ValueError, match="English-only"):
            resolve_csm_language("fr")
        with pytest.raises(ValueError, match="English-only"):
            resolve_csm_language("french")


class TestChatterboxLanguage:
    def test_french_is_default(self):
        assert resolve_chatterbox_language(None) == "fr"

    def test_iso_shorthands_and_bcp47(self):
        assert resolve_chatterbox_language("fr") == "fr"
        assert resolve_chatterbox_language("fr-fr") == "fr"
        assert resolve_chatterbox_language("EN") == "en"
        assert resolve_chatterbox_language("pt-br") == "pt"

    def test_all_documented_language_ids_pass_through(self):
        from plugins.chatterbox.plugin import _CHATTERBOX_LANGS

        for lang_id in _CHATTERBOX_LANGS:
            assert resolve_chatterbox_language(lang_id) == lang_id

    def test_unsupported_fails_loudly(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            resolve_chatterbox_language("tlh")


# --- plugin manifests ------------------------------------------------------


class TestPluginManifests:
    def test_manifests_declare_tts_engines(self):
        from common.core.registry import discover_plugins

        tool_root = Path(__file__).resolve().parents[1]
        manifests = discover_plugins({}, tool_root=tool_root)

        for name in ("csm", "chatterbox"):
            assert name in manifests
            assert issubclass(manifests[name].engine_class, TTSPlugin)

    def test_configuration_defaults_include_engines(self):
        defaults = get_default_config()
        csm = defaults["csm"]
        assert csm["model"] == "sesame/csm-1b"
        assert csm["language"] == "en"
        chatterbox = defaults["chatterbox"]
        assert chatterbox["language"] == "fr"


# --- expressivity (exaggeration) -------------------------------------------


class TestCsmExaggeration:
    def test_default_is_neutral(self):
        from plugins.csm.plugin import resolve_csm_exaggeration

        assert resolve_csm_exaggeration(None) == 0.5

    def test_out_of_range_fails_loudly(self):
        from plugins.csm.plugin import resolve_csm_exaggeration

        with pytest.raises(ValueError, match="within"):
            resolve_csm_exaggeration(2.5)
        with pytest.raises(ValueError, match="within"):
            resolve_csm_exaggeration(-0.1)

    def test_temperature_mapping(self):
        from plugins.csm.plugin import csm_temperature_from_exaggeration

        # exaggeration 0.5 == csm-1b's own default sampling temperature
        assert csm_temperature_from_exaggeration(0.5) == pytest.approx(0.9)
        assert csm_temperature_from_exaggeration(0.0) == pytest.approx(0.5)
        assert csm_temperature_from_exaggeration(1.0) == pytest.approx(1.3)
        assert csm_temperature_from_exaggeration(2.0) == pytest.approx(2.0)


class TestChatterboxExaggeration:
    def test_kwargs_override_config(self):
        v = ChatterboxTTSPlugin._resolve_exaggeration(
            {"exaggeration": 0.0}, {"exaggeration": 0.5}
        )
        assert v == 0.0

    def test_config_fallback(self):
        v = ChatterboxTTSPlugin._resolve_exaggeration({}, {"exaggeration": 1.2})
        assert v == 1.2

    def test_default_when_unconfigured(self):
        assert ChatterboxTTSPlugin._resolve_exaggeration({}, {}) == 0.5

    def test_zero_is_respected(self):
        v = ChatterboxTTSPlugin._resolve_exaggeration({"exaggeration": 0}, {})
        assert v == 0.0

    def test_out_of_range_fails_loudly(self):
        with pytest.raises(ValueError, match="within"):
            ChatterboxTTSPlugin._resolve_exaggeration({"exaggeration": 3.0}, {})


# --- chatterbox 0-shot clone cache -----------------------------------------


class TestChatterboxCloneCache:
    def test_cache_key_depends_on_file_content(self, tmp_path):
        f1 = tmp_path / "a.wav"
        f2 = tmp_path / "b.wav"
        f1.write_bytes(b"same-content")
        f2.write_bytes(b"same-content")
        f3 = tmp_path / "c.wav"
        f3.write_bytes(b"other-content")

        p1 = ChatterboxTTSPlugin._conds_cache_path(f1)
        p2 = ChatterboxTTSPlugin._conds_cache_path(f2)
        p3 = ChatterboxTTSPlugin._conds_cache_path(f3)
        assert p1 == p2
        assert p1 != p3
        assert p1.suffix == ".pt"
        assert "chatterbox" in str(p1)
        assert "ref_voices" in str(p1)


# --- synthesis guards (no model download: errors raised before loading) ----


class TestSynthesizeGuards:
    def test_csm_rejects_non_english_before_model_load(self):
        plugin = CsmPlugin(get_default_config())
        with pytest.raises(ValueError, match="English-only"):
            plugin.synthesize("bonjour", voice="0", speed=1.0, language="fr")

    def test_csm_rejects_non_numeric_voice_before_model_load(self):
        plugin = CsmPlugin(get_default_config())
        with pytest.raises(ValueError, match="numeric speaker id"):
            plugin.synthesize(
                "hello",
                voice="am_michael*0.7",
                speed=1.0,
                language="en",
            )

    def test_chatterbox_rejects_unsupported_language_before_model_load(self):
        plugin = ChatterboxTTSPlugin(get_default_config())
        with pytest.raises(ValueError, match="Unsupported language"):
            plugin.synthesize("hello", voice="", speed=1.0, language="xx")


# --- sanity ----------------------------------------------------------------


def test_sample_rate_constants():
    from plugins.csm.plugin import _CSM_SAMPLE_RATE
    from plugins.chatterbox.plugin import _CHATTERBOX_SAMPLE_RATE

    assert _CSM_SAMPLE_RATE == 24000
    assert _CHATTERBOX_SAMPLE_RATE == _CSM_SAMPLE_RATE
    assert math.isfinite(_CSM_SAMPLE_RATE)
