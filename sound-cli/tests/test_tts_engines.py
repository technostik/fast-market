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
