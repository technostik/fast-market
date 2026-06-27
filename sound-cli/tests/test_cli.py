from __future__ import annotations

import importlib

import pytest

from plugins.kokoro.plugin import resolve_kokoro_lang_code
from plugins.qwen3.plugin import resolve_qwen3_language


class TestCLICommands:
    def test_main_help(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["--help"])
        assert result.exit_code == 0
        assert "generate speech" in result.output.lower()
        assert "music" in result.output.lower()
        assert "speak" in result.output.lower()

    def test_speak_help(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["speak", "--help"])
        assert result.exit_code == 0
        assert "TEXT" in result.output
        assert "--engine" in result.output
        assert "--voice" in result.output
        assert "--speed" in result.output
        assert "--output" in result.output
        assert "-e" in result.output
        assert "-v" in result.output
        assert "-s" in result.output
        assert "-o" in result.output
        assert "--language" in result.output
        assert "-L" in result.output

    def test_speak_no_text(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["speak"])
        assert result.exit_code != 0
        assert "Error" in result.output or "Usage" in result.output

    def test_music_help(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["music", "--help"])
        assert result.exit_code == 0
        assert "PROMPT" in result.output
        assert "--duration" in result.output
        assert "--output" in result.output
        assert "-d" in result.output
        assert "-o" in result.output

    def test_music_no_prompt(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["music"])
        assert result.exit_code != 0
        assert "Error" in result.output or "Usage" in result.output


class TestKokoroPlugin:
    def test_parse_voice_string_single(self):
        from plugins.kokoro.plugin import _parse_voice_string

        names, weights = _parse_voice_string("am_michael")
        assert names == ["am_michael"]
        assert weights == [1.0]

    def test_parse_voice_string_weighted(self):
        from plugins.kokoro.plugin import _parse_voice_string

        names, weights = _parse_voice_string("am_michael*0.7,am_fenrir*0.3")
        assert names == ["am_michael", "am_fenrir"]
        assert abs(weights[0] - 0.7) < 1e-6
        assert abs(weights[1] - 0.3) < 1e-6

    def test_parse_voice_string_without_weights(self):
        from plugins.kokoro.plugin import _parse_voice_string

        names, weights = _parse_voice_string("am_michael,am_fenrir")
        assert names == ["am_michael", "am_fenrir"]
        assert abs(weights[0] - 0.5) < 1e-6
        assert abs(weights[1] - 0.5) < 1e-6

    def test_parse_voice_string_mixed_weights(self):
        from plugins.kokoro.plugin import _parse_voice_string

        names, weights = _parse_voice_string("voice_a*0.5,voice_b")
        assert names == ["voice_a", "voice_b"]
        assert abs(weights[0] - 0.333) < 0.001
        assert abs(weights[1] - 0.666) < 0.001

    def test_parse_voice_string_empty(self):
        from plugins.kokoro.plugin import _parse_voice_string

        with pytest.raises(ValueError, match="Empty voice"):
            _parse_voice_string("")


class TestKokoroLangCode:
    def test_shorthand_en(self):
        assert resolve_kokoro_lang_code("en") == "a"

    def test_shorthand_en_gb(self):
        assert resolve_kokoro_lang_code("en-gb") == "b"

    def test_shorthand_fr(self):
        assert resolve_kokoro_lang_code("fr") == "f"

    def test_shorthand_ja(self):
        assert resolve_kokoro_lang_code("ja") == "j"

    def test_shorthand_zh(self):
        assert resolve_kokoro_lang_code("zh") == "z"

    def test_human_readable_french(self):
        assert resolve_kokoro_lang_code("French") == "f"

    def test_human_readable_mandarin(self):
        assert resolve_kokoro_lang_code("Mandarin Chinese") == "z"

    def test_raw_code_f(self):
        assert resolve_kokoro_lang_code("f") == "f"

    def test_raw_code_b(self):
        assert resolve_kokoro_lang_code("b") == "b"

    def test_none_returns_default(self):
        assert resolve_kokoro_lang_code(None) == "a"

    def test_unknown_returns_default(self):
        assert resolve_kokoro_lang_code("xyz") == "a"

    def test_empty_returns_default(self):
        assert resolve_kokoro_lang_code("") == "a"

    def test_case_insensitive(self):
        assert resolve_kokoro_lang_code("EN") == "a"
        assert resolve_kokoro_lang_code("Fr") == "f"

    def test_underscore_normalised(self):
        assert resolve_kokoro_lang_code("en_gb") == "b"
        assert resolve_kokoro_lang_code("pt_br") == "p"


class TestQwen3Language:
    def test_shorthand_en(self):
        assert resolve_qwen3_language("en") == "English"

    def test_shorthand_zh(self):
        assert resolve_qwen3_language("zh") == "Chinese"

    def test_shorthand_ja(self):
        assert resolve_qwen3_language("ja") == "Japanese"

    def test_shorthand_ko(self):
        assert resolve_qwen3_language("ko") == "Korean"

    def test_shorthand_fr(self):
        assert resolve_qwen3_language("fr") == "French"

    def test_human_readable(self):
        assert resolve_qwen3_language("German") == "German"
        assert resolve_qwen3_language("russian") == "Russian"

    def test_none_returns_english(self):
        assert resolve_qwen3_language(None) == "English"

    def test_unknown_returns_english(self):
        assert resolve_qwen3_language("xyz") == "English"

    def test_case_insensitive(self):
        assert resolve_qwen3_language("EN") == "English"
        assert resolve_qwen3_language("Fr") == "French"


class TestModels:
    def test_tts_request(self):
        from core.models import TTSRequest

        req = TTSRequest(text="Hello", engine="kokoro", voice="am_michael")
        assert req.text == "Hello"
        assert req.engine == "kokoro"

    def test_tts_result_to_dict(self):
        from core.models import TTSResult
        from pathlib import Path

        result = TTSResult(
            path=Path("/tmp/test.wav"),
            text="Hello",
            voice="am_michael",
            engine="kokoro",
            duration_secs=2.5,
            sample_rate=24000,
        )
        data = result.to_dict()
        assert data["path"] == "/tmp/test.wav"
        assert data["duration_secs"] == 2.5

    def test_music_result_to_dict(self):
        from core.models import MusicGenResult
        from pathlib import Path

        result = MusicGenResult(
            path=Path("/tmp/music.wav"),
            prompt="lofi piano",
            engine="musicgen",
            duration_secs=5.0,
            sample_rate=32000,
        )
        data = result.to_dict()
        assert data["path"] == "/tmp/music.wav"
        assert data["prompt"] == "lofi piano"
        assert data["duration_secs"] == 5.0
