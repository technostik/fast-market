from __future__ import annotations

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "diagnose",
        help="Run diagnostic tests to diagnose YouTube sync issues",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.option(
        "--source",
        "source_name",
        type=click.Choice(["youtube", "obsidian"]),
        default="youtube",
        help="Source to diagnose",
    )
    @click.pass_context
    def diagnose_cmd(ctx, fmt, source_name, **kwargs):
        from common.core.config import load_config

        config = load_config()

        if source_name == "youtube":
            results = _run_youtube_diagnostics(config)
        elif source_name == "obsidian":
            results = _run_obsidian_diagnostics(config)
        else:
            raise click.ClickException(f"Unknown source: {source_name}")

        if fmt == "text":
            _print_results_text(results)
        else:
            out([r.to_dict() for r in results], fmt)

    return CommandManifest(
        name="diagnose",
        click_command=diagnose_cmd,
    )


def _run_youtube_diagnostics(config: dict) -> list:
    from common.youtube.diagnose import (
        check_api_credentials,
        check_network_connectivity,
        check_oauth_token,
        check_quota_usage,
        test_api_client,
        test_rss_feed,
    )

    results = []

    results.append(check_oauth_token(config))
    results.append(check_network_connectivity())
    results.append(check_api_credentials(config))
    results.append(test_rss_feed(config))

    api_result = test_api_client(config)
    results.append(api_result)

    if api_result.status != "error" or "quota" not in api_result.message.lower():
        results.append(check_quota_usage(config))

    return results


def _run_obsidian_diagnostics(config: dict) -> list:
    from common.youtube.diagnose import DiagnosticResult

    results = []

    vault_path = config.get("obsidian", {}).get("vault_path")
    if not vault_path:
        results.append(
            DiagnosticResult(
                "config",
                "error",
                "No obsidian.vault_path in config",
                {},
            )
        )
        return results

    from pathlib import Path

    vault = Path(vault_path).expanduser()
    if not vault.exists():
        results.append(
            DiagnosticResult(
                "vault",
                "error",
                f"Vault path does not exist: {vault}",
                {},
            )
        )
    else:
        results.append(
            DiagnosticResult(
                "vault",
                "ok",
                f"Vault exists at: {vault}",
                {"vault_path": str(vault)},
            )
        )

        md_files = list(vault.glob("**/*.md"))
        results.append(
            DiagnosticResult(
                "files",
                "ok",
                f"Found {len(md_files)} markdown files",
                {"file_count": len(md_files)},
            )
        )

    return results


def _print_results_text(results: list) -> None:
    ok_count = error_count = warning_count = 0

    for r in results:
        status = r.status
        if status == "ok":
            ok_count += 1
        elif status == "error":
            error_count += 1
        else:
            warning_count += 1

        click.echo(f"[{status.upper()}] {r.test_name}: {r.message}")
        if r.details:
            for key, value in r.details.items():
                click.echo(f"    {key}: {value}")

    click.echo()
    click.echo(f"Summary: {ok_count} ok, {warning_count} warning, {error_count} error")

    if error_count > 0:
        click.echo()
        click.echo("Recommendations:")
        for r in results:
            if r.status == "error":
                rec = _get_recommendation(r.test_name, r.message)
                if rec:
                    click.echo(f"  - {rec}")


def _get_recommendation(test: str, message: str) -> str | None:
    message_lower = message.lower()

    if test == "oauth_token":
        if "expired" in message_lower or "invalid" in message_lower:
            return "Delete token.json and run `corpus sync` to re-authenticate"
        if "not found" in message_lower:
            return "Run `corpus sync` to trigger OAuth flow"

    if test == "api_credentials":
        if "not found" in message_lower:
            return "Set up YouTube API credentials in ~/.config/fast-market/common/youtube/client_secret.json"

    if test == "rss_feed":
        if "error" in message_lower:
            return "RSS feed failed - check channel_id in config"
        if "no videos" in message_lower:
            return "Check channel_id is correct"

    if "quota exceeded" in message_lower:
        return "Wait for quota to reset (typically midnight PST) or use --non-public for RSS mode"

    if "authentication failed" in message_lower or "401" in message_lower:
        return "Token may be expired - delete ~/.config/fast-market/common/youtube/token.json and re-authenticate"

    return None