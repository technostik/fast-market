from __future__ import annotations

import click
from pathlib import Path

from common.core.config import load_common_config, load_llm_config, load_youtube_config


class DiagnosticResult:
    def __init__(
        self,
        test_name: str,
        status: str,
        message: str,
        details: dict | None = None,
        recommendations: list[str] | None = None,
    ):
        self.test_name = test_name
        self.status = status  # "ok", "warning", "error"
        self.message = message
        self.details = details or {}
        self.recommendations = recommendations or []

    def to_dict(self) -> dict:
        return {
            "test": self.test_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "recommendations": self.recommendations,
        }


def check_workdir_health() -> DiagnosticResult:
    """Check workdir configuration and existence."""
    config = load_common_config()
    workdir = config.get("workdir")
    workdir_root = config.get("workdir_root")

    if not workdir:
        return DiagnosticResult(
            "workdir",
            "warning",
            "No workdir configured",
            {"workdir": workdir},
            ["Run 'toolsetup workdir init <path>' to set up a workdir"],
        )

    workdir_path = Path(workdir).expanduser().resolve()

    if not workdir_path.exists():
        recommendations = []
        if workdir_root:
            root_path = Path(workdir_root).expanduser().resolve()
            if root_path.exists():
                recommendations.append(
                    f"Run 'toolsetup workdir reset' to reset workdir to {root_path}"
                )
            else:
                recommendations.append(
                    f"Run 'toolsetup workdir init <path>' to recreate workdir_root"
                )

        return DiagnosticResult(
            "workdir",
            "error",
            f"Configured workdir does not exist: {workdir_path}",
            {"workdir": str(workdir_path), "workdir_root": workdir_root},
            recommendations,
        )

    return DiagnosticResult(
        "workdir",
        "ok",
        f"Workdir exists: {workdir_path}",
        {"workdir": str(workdir_path)},
    )


def check_llm_health(provider: str | None = None) -> DiagnosticResult:
    """Check LLM connectivity by attempting a simple request."""
    try:
        llm_config = load_llm_config()
    except Exception as e:
        return DiagnosticResult(
            "llm",
            "warning",
            f"LLM config not found or invalid: {e}",
            {},
            ["Run 'toolsetup llm add <provider>' to configure an LLM provider"],
        )

    providers = llm_config.get("providers", {})
    default_provider = llm_config.get("default_provider")

    if not providers:
        return DiagnosticResult(
            "llm",
            "warning",
            "No LLM providers configured",
            {},
            ["Run 'toolsetup llm add <provider>' to configure an LLM provider"],
        )

    test_provider = provider or default_provider

    if not test_provider:
        return DiagnosticResult(
            "llm",
            "warning",
            "No default LLM provider set",
            {"available_providers": list(providers.keys())},
            ["Run 'toolsetup llm set-default <provider>' to set a default provider"],
        )

    if test_provider not in providers:
        return DiagnosticResult(
            "llm",
            "error",
            f"Provider '{test_provider}' not in configured providers",
            {
                "requested_provider": test_provider,
                "available_providers": list(providers.keys()),
            },
            ["Run 'toolsetup llm add <provider>' to add the provider" if provider else "Run 'toolsetup llm set-default <provider>' with a valid provider"],
        )

    # Try to instantiate the provider
    try:
        from common.llm.registry import discover_providers
        from common.llm.base import LLMRequest

        discovered_providers = discover_providers(llm_config)
        if test_provider not in discovered_providers:
            return DiagnosticResult(
                "llm",
                "error",
                f"Failed to initialize provider '{test_provider}'",
                {"error": "Provider initialization failed"},
                ["Check API key environment variables and provider configuration"],
            )

        test_llm_provider = discovered_providers[test_provider]

        # Simple test request
        test_request = LLMRequest(
            prompt="Hello, please respond with 'OK' if you can read this.",
            model=providers[test_provider].get("model", "default"),
            temperature=0.0,
            max_tokens=10,
        )

        response = test_llm_provider.complete(test_request)

        if response and response.content.strip():
            return DiagnosticResult(
                "llm",
                "ok",
                f"LLM connectivity successful ({test_provider})",
                {
                    "provider": test_provider,
                    "model": response.model,
                    "response_length": len(response.content),
                },
            )
        else:
            return DiagnosticResult(
                "llm",
                "warning",
                f"LLM responded but with empty content ({test_provider})",
                {
                    "provider": test_provider,
                    "model": response.model if response else None,
                },
            )

    except Exception as e:
        error_msg = str(e).lower()
        recommendations = ["Check API key environment variables"]

        if "quota" in error_msg or "limit" in error_msg:
            recommendations.append("Check API quota/limits")
        elif "auth" in error_msg or "key" in error_msg:
            recommendations.append("Verify API key is set correctly")
        elif "network" in error_msg or "connect" in error_msg:
            recommendations.append("Check network connectivity")
        elif "timeout" in error_msg:
            recommendations.append(
                "Check if the LLM service is running (for local providers)"
            )

        return DiagnosticResult(
            "llm",
            "error",
            f"LLM test failed ({test_provider}): {e}",
            {"provider": test_provider, "error": str(e)},
            recommendations,
        )


def check_youtube_health() -> list[DiagnosticResult]:
    """Run YouTube diagnostics."""
    try:
        from common.youtube.diagnose import run_all_diagnostics

        yt_config = load_youtube_config()
        results = run_all_diagnostics(yt_config)

        # Convert to our DiagnosticResult format
        converted = []
        for result in results:
            recommendations = []
            if result.status == "error":
                # Add some recommendations based on test name
                if result.test_name == "oauth_token":
                    recommendations.append(
                        "Run 'corpus sync' or 'youtube sync' to re-authenticate"
                    )
                elif result.test_name == "api_credentials":
                    recommendations.append(
                        "Set up YouTube API credentials in client_secret.json"
                    )
                elif result.test_name == "network":
                    recommendations.append("Check internet connectivity")
                elif "quota" in result.message.lower():
                    recommendations.append(
                        "Wait for quota reset or use RSS fallback mode"
                    )

            converted.append(
                DiagnosticResult(
                    f"youtube_{result.test_name}",
                    result.status,
                    result.message,
                    result.details,
                    recommendations,
                )
            )

        return converted

    except Exception as e:
        return [
            DiagnosticResult(
                "youtube",
                "warning",
                f"YouTube diagnostics unavailable: {e}",
                {"error": str(e)},
                ["Ensure YouTube tools are properly installed"],
            )
        ]


def check_groq_transcription_health() -> DiagnosticResult:
    """Check Groq API transcription by transcribing the test fixture clip."""
    import os
    import subprocess
    import tempfile

    repo_root = Path(__file__).parent.parent.parent.parent
    fixture = repo_root / "video-cli" / "tests" / "fixtures" / "publish" / "test_clip.mkv"

    # Try loading .env from repo root (best-effort)
    try:
        from dotenv import load_dotenv
        load_dotenv(repo_root / ".env")
    except ImportError:
        pass

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return DiagnosticResult(
            "groq_transcription",
            "error",
            "GROQ_API_KEY environment variable not set",
            {},
            ["Set GROQ_API_KEY in your environment or .env file"],
        )

    if not fixture.exists():
        return DiagnosticResult(
            "groq_transcription",
            "error",
            f"Test fixture not found: {fixture}",
            {"fixture": str(fixture)},
            ["Run from the repo root or check video-cli/tests/fixtures/publish/test_clip.mkv exists"],
        )

    try:
        import requests
    except ImportError:
        return DiagnosticResult(
            "groq_transcription",
            "error",
            "requests library not available",
            {},
            ["Install requests: pip install requests"],
        )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_audio = tmp.name

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(fixture), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", tmp_audio],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass
        return DiagnosticResult(
            "groq_transcription",
            "error",
            "ffmpeg not found — required to extract audio for transcription",
            {},
            ["Install ffmpeg: sudo apt install ffmpeg (or equivalent)"],
        )
    except subprocess.CalledProcessError as e:
        details = {"returncode": e.returncode, "stderr": e.stderr.decode() if e.stderr else ""}
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass
        return DiagnosticResult(
            "groq_transcription",
            "error",
            f"ffmpeg failed to extract audio from test clip",
            details,
            ["Check that the test clip file is valid"],
        )

    try:
        form_data = [
            ("model", "whisper-large-v3"),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
            ("language", "fr"),
        ]
        with open(tmp_audio, "rb") as f:
            resp = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("test_clip.mp3", f, "audio/mpeg")},
                data=form_data,
                timeout=120,
            )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        body = e.response.text if e.response is not None else ""
        recommendations = []
        if status == 401:
            recommendations.append(
                "Verify GROQ_API_KEY is valid at console.groq.com — key may have been rotated or revoked"
            )
        elif status == 403:
            recommendations.append("Check that whisper-large-v3 is accessible on your Groq account")
        elif status == 429:
            recommendations.append("Groq API rate limit hit — wait and retry")
        else:
            recommendations.append("Check Groq API status and your account's model access")
        return DiagnosticResult(
            "groq_transcription",
            "error",
            f"Groq API returned HTTP {status}",
            {"status_code": status, "response_body": body},
            recommendations,
        )
    except requests.exceptions.Timeout:
        return DiagnosticResult(
            "groq_transcription",
            "error",
            "Groq API request timed out after 120s",
            {},
            ["Check network connectivity or try again later"],
        )
    except requests.exceptions.ConnectionError as e:
        return DiagnosticResult(
            "groq_transcription",
            "error",
            f"Could not connect to Groq API: {e}",
            {},
            ["Check internet connectivity"],
        )
    except requests.exceptions.RequestException as e:
        return DiagnosticResult(
            "groq_transcription",
            "error",
            f"Groq API request failed: {e}",
            {},
            ["Check network connectivity and API endpoint URL"],
        )
    finally:
        try:
            os.unlink(tmp_audio)
        except Exception:
            pass

    text = (result or {}).get("text", "")
    word_count = len((result or {}).get("words", []))
    details = {"text_length": len(text), "word_count": word_count}
    if text:
        details["transcript_preview"] = text[:120]
    else:
        details["transcript_preview"] = ""

    if text:
        return DiagnosticResult(
            "groq_transcription",
            "ok",
            f"Groq transcription successful ({word_count} words)",
            details,
        )
    else:
        return DiagnosticResult(
            "groq_transcription",
            "warning",
            "Groq returned empty transcription",
            details,
            ["Check that the test clip contains audible speech"],
        )


def run_all_diagnostics(provider: str | None = None) -> list[DiagnosticResult]:
    """Run all diagnostic checks."""
    results = []

    # Workdir check
    results.append(check_workdir_health())

    # LLM check
    results.append(check_llm_health(provider=provider))

    # YouTube checks
    results.extend(check_youtube_health())

    # Groq transcription check
    results.append(check_groq_transcription_health())

    return results


def print_diagnostic_results(
    results: list[DiagnosticResult], format_type: str = "text"
) -> None:
    """Print diagnostic results in the requested format."""
    if format_type == "json":
        import json

        output = [r.to_dict() for r in results]
        click.echo(json.dumps(output, indent=2))
        return

    # Text format
    ok_count = sum(1 for r in results if r.status == "ok")
    warning_count = sum(1 for r in results if r.status == "warning")
    error_count = sum(1 for r in results if r.status == "error")

    for result in results:
        status_icon = {"ok": "✓", "warning": "⚠", "error": "✗"}.get(result.status, "?")
        click.echo(f"[{status_icon}] {result.test_name}: {result.message}")

        if result.details:
            for key, value in result.details.items():
                click.echo(f"    {key}: {value}")

        if result.recommendations and result.status in ("warning", "error"):
            click.echo("    Recommendations:")
            for rec in result.recommendations:
                click.echo(f"      • {rec}")

        click.echo()

    # Summary
    click.echo("=" * 50)
    click.echo(f"Summary: {ok_count} ok, {warning_count} warning, {error_count} error")

    if error_count > 0 or warning_count > 0:
        click.echo()
        click.echo("For detailed help:")
        click.echo("  - toolsetup --show          # Show current config")
        click.echo("  - toolsetup workdir <path>  # Fix workdir issues")
        click.echo("  - toolsetup llm add <prov>  # Configure LLM providers")
        if any(
            r.test_name.startswith("youtube_") and r.status != "ok" for r in results
        ):
            click.echo("  - corpus setup              # Fix YouTube issues")
