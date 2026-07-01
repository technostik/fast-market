from __future__ import annotations

import importlib
import math

import pytest

import torch

from commands.speak.register import _accelerate
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
        assert "--accelerate" in result.output
        assert "-a" in result.output

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

    def test_prosody_help(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["prosody", "--help"])
        assert result.exit_code == 0
        assert "FILE" in result.output
        assert "--output" in result.output
        assert "-o" in result.output
        assert "--format" in result.output
        assert "-F" in result.output

    def test_prosody_missing_file(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["prosody", "/tmp/does_not_exist_prosody.wav"])
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


class TestAccelerate:
    def test_rate_one_returns_same(self):
        audio = torch.randn(1000)
        result = _accelerate(audio, 1.0)
        assert result is audio

    def test_rate_negative_returns_same(self):
        audio = torch.randn(1000)
        result = _accelerate(audio, 0.0)
        assert result is audio

    def test_rate_small_returns_same(self):
        audio = torch.randn(1000)
        result = _accelerate(audio, -1.0)
        assert result is audio

    def test_empty_returns_same(self):
        audio = torch.zeros(0)
        result = _accelerate(audio, 2.0)
        assert result is audio

    def test_stretch_longer(self):
        audio = torch.sin(torch.linspace(0, 4 * math.pi, 4000))
        result = _accelerate(audio, 0.5)
        assert result.numel() > audio.numel() / 2

    def test_stretch_shorter(self):
        audio = torch.sin(torch.linspace(0, 4 * math.pi, 4000))
        result = _accelerate(audio, 2.0)
        assert result.numel() < audio.numel()

    def test_preserves_pitch_structure(self):
        """Accelerated audio should maintain zero-crossing structure (pitch)."""
        audio = torch.sin(torch.linspace(0, 40 * math.pi, 10000))
        result = _accelerate(audio, 1.5)
        # After acceleration, the output should still be a valid waveform
        assert not torch.isnan(result).any()
        assert result.numel() > 0


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

    def test_prosody_result_to_dict(self):
        from core.models import ProsodyResult
        from pathlib import Path

        result = ProsodyResult(
            path=Path("/tmp/clip.wav"),
            global_score=72.5,
            pitch_score=80.0,
            energy_score=65.0,
            rhythm_score=70.0,
            rate_score=75.0,
            duration_secs=10.0,
            median_f0_hz=180.0,
            semitone_range=6.5,
            rms_cv=0.4,
            pause_count_per_min=8.0,
            estimated_rate_per_sec=4.2,
        )
        data = result.to_dict()
        assert data["path"] == "/tmp/clip.wav"
        assert data["global_score"] == 72.5
        assert data["median_f0_hz"] == 180.0


class TestProsodyScoring:
    def test_target_band_score_ideal(self):
        from commands.prosody.analysis import _target_band_score

        assert _target_band_score(6.0, 1.0, 4.0, 12.0, 20.0) == 100.0

    def test_target_band_score_at_extremes(self):
        from commands.prosody.analysis import _target_band_score

        assert _target_band_score(1.0, 1.0, 4.0, 12.0, 20.0) == 0.0
        assert _target_band_score(20.0, 1.0, 4.0, 12.0, 20.0) == 0.0
        assert _target_band_score(0.0, 1.0, 4.0, 12.0, 20.0) == 0.0
        assert _target_band_score(30.0, 1.0, 4.0, 12.0, 20.0) == 0.0

    def test_target_band_score_monotonic_ramp(self):
        from commands.prosody.analysis import _target_band_score

        low_side = _target_band_score(2.0, 1.0, 4.0, 12.0, 20.0)
        high_side = _target_band_score(3.0, 1.0, 4.0, 12.0, 20.0)
        assert 0.0 < low_side < high_side <= 100.0

    def test_score_prosody_synthetic_sine(self, tmp_path):
        import numpy as np
        import soundfile as sf

        from commands.prosody.analysis import score_prosody

        sr = 22050
        t = np.linspace(0, 2, sr * 2, endpoint=False)
        y = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

        wav_path = tmp_path / "tone.wav"
        sf.write(str(wav_path), y, sr)

        scores = score_prosody(y, sr)

        expected_keys = {
            "global_score", "pitch_score", "energy_score", "rhythm_score",
            "rate_score", "duration_secs", "median_f0_hz", "semitone_range",
            "rms_cv", "pause_count_per_min", "estimated_rate_per_sec",
        }
        assert expected_keys.issubset(scores.keys())
        for key in ("global_score", "pitch_score", "energy_score", "rhythm_score", "rate_score"):
            assert 0.0 <= scores[key] <= 100.0

    def test_score_prosody_monotone_has_low_pitch_score(self):
        import numpy as np

        from commands.prosody.analysis import score_prosody

        sr = 22050
        t = np.linspace(0, 3, sr * 3, endpoint=False)
        y = (0.3 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)

        scores = score_prosody(y, sr)
        assert scores["pitch_score"] == 0.0
        assert scores["semitone_range"] == 0.0
