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


def check_llm_health() -> DiagnosticResult:
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

    if not default_provider:
        return DiagnosticResult(
            "llm",
            "warning",
            "No default LLM provider set",
            {"available_providers": list(providers.keys())},
            ["Run 'toolsetup llm set-default <provider>' to set a default provider"],
        )

    if default_provider not in providers:
        return DiagnosticResult(
            "llm",
            "error",
            f"Default provider '{default_provider}' not in configured providers",
            {
                "default_provider": default_provider,
                "available_providers": list(providers.keys()),
            },
            ["Run 'toolsetup llm set-default <provider>' with a valid provider"],
        )

    # Try to instantiate the provider
    try:
        from common.llm.registry import discover_providers
        from common.llm.base import LLMRequest

        discovered_providers = discover_providers(llm_config)
        if default_provider not in discovered_providers:
            return DiagnosticResult(
                "llm",
                "error",
                f"Failed to initialize provider '{default_provider}'",
                {"error": "Provider initialization failed"},
                ["Check API key environment variables and provider configuration"],
            )

        provider = discovered_providers[default_provider]

        # Simple test request
        test_request = LLMRequest(
            prompt="Hello, please respond with 'OK' if you can read this.",
            model=providers[default_provider].get("model", "default"),
            temperature=0.0,
            max_tokens=10,
        )

        response = provider.complete(test_request)

        if response and response.content.strip():
            return DiagnosticResult(
                "llm",
                "ok",
                f"LLM connectivity successful ({default_provider})",
                {
                    "provider": default_provider,
                    "model": response.model,
                    "response_length": len(response.content),
                },
            )
        else:
            return DiagnosticResult(
                "llm",
                "warning",
                f"LLM responded but with empty content ({default_provider})",
                {
                    "provider": default_provider,
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
            f"LLM test failed ({default_provider}): {e}",
            {"provider": default_provider, "error": str(e)},
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


def run_all_diagnostics() -> list[DiagnosticResult]:
    """Run all diagnostic checks."""
    results = []

    # Workdir check
    results.append(check_workdir_health())

    # LLM check
    results.append(check_llm_health())

    # YouTube checks
    results.extend(check_youtube_health())

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
