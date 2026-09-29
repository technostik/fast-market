from __future__ import annotations

import importlib


class TestTranscribeCommand:
    def test_transcribe_help(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["transcribe", "--help"])
        assert result.exit_code == 0
        assert "FILE" in result.output
        assert "--engine" in result.output
        assert "--modal" in result.output
        assert "--output" in result.output
        assert "--format" in result.output
        assert "--language" in result.output
        assert "--model" in result.output

    def test_transcribe_missing_file(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["transcribe", "/tmp/does_not_exist_transcribe.wav"])
        assert result.exit_code != 0

    def test_transcribe_discovered(self, runner):
        import cli.main as cli_mod

        importlib.reload(cli_mod)
        result = runner.invoke(cli_mod.main, ["--help"])
        assert result.exit_code == 0
        assert "transcribe" in result.output


class TestResolveEngine:
    def _no_dotenv(self, monkeypatch):
        import commands.transcribe.analysis as analysis

        # Stub .env loading so tests control the env explicitly
        # (in production resolve_engine loads the repo .env best-effort).
        monkeypatch.setattr(analysis, "_load_env", lambda: None)

    def test_explicit_passthrough(self, monkeypatch):
        from commands.transcribe.analysis import resolve_engine

        self._no_dotenv(monkeypatch)

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        assert resolve_engine("local", {}) == "local"
        assert resolve_engine("groq", {}) == "groq"
        assert resolve_engine("cloudflare", {}) == "cloudflare"
        assert resolve_engine("modal", {}) == "modal"

    def test_auto_prefers_groq(self, monkeypatch):
        from commands.transcribe.analysis import resolve_engine

        self._no_dotenv(monkeypatch)

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        assert resolve_engine("auto", {}) == "groq"

    def test_auto_falls_back_to_cloudflare(self, monkeypatch):
        from commands.transcribe.analysis import resolve_engine

        self._no_dotenv(monkeypatch)

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
        assert resolve_engine("auto", {}) == "cloudflare"

    def test_auto_cloudflare_from_config(self, monkeypatch):
        from commands.transcribe.analysis import resolve_engine

        self._no_dotenv(monkeypatch)

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        config = {"transcribe": {"cloudflare": {"account_id": "a", "api_token": "t"}}}
        assert resolve_engine("auto", config) == "cloudflare"

    def test_auto_falls_back_to_local(self, monkeypatch):
        from commands.transcribe.analysis import resolve_engine

        self._no_dotenv(monkeypatch)

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        assert resolve_engine("auto", {}) == "local"


class TestSrtFormatting:
    def test_to_srt(self):
        from commands.transcribe.analysis import to_srt

        segments = [
            {"start": 0.5, "end": 2.0, "text": "Hello world"},
            {"start": 65.25, "end": 3661.5, "text": "Second line"},
        ]
        srt = to_srt(segments)
        assert "1\n00:00:00,500 --> 00:00:02,000\nHello world" in srt
        assert "2\n00:01:05,250 --> 01:01:01,500\nSecond line" in srt

    def test_to_srt_empty(self):
        from commands.transcribe.analysis import to_srt

        assert to_srt([]) == ""
