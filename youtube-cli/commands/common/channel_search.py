from __future__ import annotations

from core.config import load_config
from core.engine import build_youtube_client


def search_channels(query: str, max_results: int = 10) -> list[dict]:
    """Search for YouTube channels by name.

    Returns list of dicts:
        channel_id, title, custom_url, subscriber_count, description
    """
    config = load_config()
    client = build_youtube_client(config)

    try:
        request = client.youtube.search().list(
            part="snippet",
            q=query,
            type="channel",
            maxResults=min(max_results, 50),
            relevanceLanguage="en",
        )
        response = request.execute()
        client._track_quota(100)
    except Exception as e:
        raise RuntimeError(f"Channel search failed: {e}") from e

    channel_ids = [
        item["snippet"]["channelId"]
        for item in response.get("items", [])
    ]

    if not channel_ids:
        return []

    try:
        channels_response = client.youtube.channels().list(
            part="snippet,statistics",
            id=",".join(channel_ids[:50]),
        ).execute()
        client._track_quota(1)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch channel details: {e}") from e

    results = []
    for item in channels_response.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        results.append({
            "channel_id": item["id"],
            "title": snippet.get("title", "Unknown"),
            "custom_url": snippet.get("customUrl"),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "description": snippet.get("description", ""),
        })

    # Sort by subscriber count (most first)
    results.sort(key=lambda x: x["subscriber_count"], reverse=True)

    return results


def format_channel_entry(ch: dict, index: int) -> str:
    """Format a channel for display."""
    subs = f"{ch['subscriber_count']:,}" if ch['subscriber_count'] else "N/A"
    url = f" (@{ch['custom_url']})" if ch.get("custom_url") else ""
    return (
        f"  [{index}] {ch['title']}{url}\n"
        f"      ID: {ch['channel_id']} | Subs: {subs}\n"
        f"      {ch.get('description', '')}"
    )


def select_channel_interactive(results: list[dict]) -> dict:
    """Display channel results and prompt user to select one.

    Returns the selected channel dict.
    """
    import click

    click.echo(f"\nFound {len(results)} channels:")
    for i, ch in enumerate(results, 1):
        click.echo(format_channel_entry(ch, i))
        click.echo("")

    choice = input(f"Select channel (1-{len(results)}): ").strip()
    if not choice or not choice.isdigit():
        raise click.ClickException("Invalid selection.")

    idx = int(choice) - 1
    if idx < 0 or idx >= len(results):
        raise click.ClickException("Invalid selection.")

    return results[idx]
