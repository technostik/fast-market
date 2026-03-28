from __future__ import annotations

import asyncio
from pathlib import Path

import click
import yaml
from telegram import Update

from common.core.yaml_utils import dump_yaml
from telegram.ext import Application, MessageHandler, filters

from commands.base import CommandManifest
from core.config import load_config


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("setup")
    @click.option(
        "--plugin",
        type=click.Choice(["telegram"]),
        default="telegram",
        help="Plugin to configure",
    )
    @click.option(
        "-c",
        "--show-config",
        is_flag=True,
        help="Show current configuration",
    )
    @click.option(
        "-p",
        "--show-config-path",
        is_flag=True,
        help="Show configuration file path",
    )
    @click.pass_context
    def setup_cmd(ctx, plugin, show_config, show_config_path, **kwargs):
        config_path = _get_config_path()

        if show_config_path:
            click.echo(str(config_path))
            return

        if show_config:
            config = load_config()
            if config:
                click.echo(dump_yaml(config))
            else:
                click.echo("(no configuration found)")
            return

        click.echo(f"Setting up {plugin} plugin...")
        click.echo("")

        if plugin == "telegram":
            _setup_telegram(config_path)

    return CommandManifest(
        name="setup",
        click_command=setup_cmd,
    )


def _get_config_path() -> Path:
    from common.core.paths import get_tool_config

    path = get_tool_config("message")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _setup_telegram(config_path: Path):
    existing_config = {}
    if config_path.exists():
        existing_config = yaml.safe_load(config_path.read_text()) or {}

    telegram_config = existing_config.get("telegram", {})

    click.echo("=== Telegram Bot Setup ===")
    click.echo("")
    click.echo("To create a bot:")
    click.echo("1. Open Telegram and search for @BotFather")
    click.echo("2. Send /newbot command")
    click.echo("3. Follow the prompts to name your bot")
    click.echo("4. Copy the bot token (starts with '123456789:ABCdef...')")
    click.echo("")

    bot_token = click.prompt(
        "Enter your bot token",
        default=telegram_config.get("bot_token", ""),
        hide_input=True,
    ).strip()

    default_timeout = click.prompt(
        "Default timeout in seconds (0 = no timeout)",
        default=telegram_config.get("default_timeout", 300),
        type=int,
    )

    default_wait_for_ack = click.confirm(
        "Wait for acknowledgment by default?",
        default=telegram_config.get("default_wait_for_ack", False),
    )

    new_config = {
        **existing_config,
        "telegram": {
            "bot_token": bot_token,
            "allowed_chat_id": telegram_config.get("allowed_chat_id"),
            "default_timeout": default_timeout,
            "default_wait_for_ack": default_wait_for_ack,
        },
    }

    config_path.write_text(dump_yaml(new_config))
    click.echo(f"\nConfiguration saved to: {config_path}")

    if not bot_token:
        return

    click.echo("\nTesting connection and capturing chat ID...")
    asyncio.run(_test_and_capture(bot_token, telegram_config, config_path, new_config))


async def _test_and_capture(bot_token, telegram_config, config_path, new_config):
    import time

    chat_id_captured = {"id": None}

    async def _handle_first_message(update: Update) -> None:
        if update.effective_chat:
            chat_id_captured["id"] = update.effective_chat.id
            click.echo(f"\nDetected your chat ID: {chat_id_captured['id']}")

    app = Application.builder().token(bot_token).build()
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            _handle_first_message,
        )
    )

    await app.initialize()
    await app.start()

    try:
        me = await app.bot.get_me()
        click.echo(f"Connection successful! Bot username: @{me.username}")
    except Exception as e:
        click.echo(f"Connection failed: {e}")
        await app.stop()
        await app.shutdown()
        return

    if not telegram_config.get("allowed_chat_id"):
        click.echo("")
        click.echo("Waiting for you to send a message to your bot...")
        click.echo("(Press Ctrl+C to skip)")

        try:
            timeout_seconds = 60
            start = time.time()
            while chat_id_captured["id"] is None:
                try:
                    updates = await app.bot.get_updates(timeout=1)
                    for update in updates:
                        await _handle_first_message(update)
                except Exception:
                    pass
                if time.time() - start > timeout_seconds:
                    click.echo("\nTimeout reached. No message received.")
                    break
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            click.echo("\nSkipped chat ID capture.")

    await app.stop()
    await app.shutdown()

    if chat_id_captured["id"]:
        new_config["telegram"]["allowed_chat_id"] = chat_id_captured["id"]
        config_path.write_text(dump_yaml(new_config))
        click.echo(f"\nChat ID saved: {chat_id_captured['id']}")
        click.echo("Your bot is now configured and ready!")
    elif not telegram_config.get("allowed_chat_id"):
        click.echo("")
        click.echo("No chat ID captured.")
        click.echo("Send a message to your bot now, then run:")
        click.echo("  message setup --plugin telegram")
        click.echo("")
        click.echo("Or edit config manually: " + str(config_path))
