from __future__ import annotations

import asyncio
import time
import threading
from typing import Any

from telegram import Update
from telegram.ext import Application

from common import structlog
from common.message_targets import (
    CHAT_TYPES,
    TargetError,
    normalize_chat_ref,
    resolve_target,
)
from plugins.base import MessagePlugin

logger = structlog.get_logger(__name__)


class TelegramPlugin(MessagePlugin):
    name = "telegram"

    def __init__(self, config: dict):
        self.config = config
        tg_config = config.get("telegram", {})
        self.tg_config = tg_config
        self.bot_token = tg_config.get("bot_token")
        self.allowed_chat_id = tg_config.get("allowed_chat_id")
        self.default_timeout = tg_config.get("default_timeout", 300)
        self.default_wait_for_ack = tg_config.get("default_wait_for_ack", False)

        self._app: Application | None = None
        self._setup_lock = threading.Lock()
        self._last_update_id: int = 0
        self._initialized: bool = False

    def _ensure_app(self) -> Application:
        if self._app is None:
            with self._setup_lock:
                if self._app is None:
                    if not self.bot_token:
                        raise RuntimeError(
                            "Telegram bot token not configured. Run 'message setup --plugin telegram' first."
                        )
                    self._app = Application.builder().token(self.bot_token).build()
        return self._app

    def resolve_chat(self, target: str | None = None) -> tuple[str, int]:
        """Resolve a CLI target (named id, raw chat id or None) to a chat id."""
        return resolve_target(self.tg_config, target)

    def send_message(
        self, text: str, parse_mode: str = "HTML", target: str | None = None
    ) -> int:
        target_id, chat_id = self.resolve_chat(target)

        app = self._ensure_app()

        async def _send():
            await app.initialize()
            try:
                message = await app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                )
                return message.message_id
            finally:
                await app.shutdown()

        logger.debug("telegram_send", target=target_id, chat_id=chat_id)
        return asyncio.run(_send())

    def wait_for_reply(self, timeout: int, target: str | None = None) -> str:
        _, chat_id = self.resolve_chat(target)
        app = self._ensure_app()

        async def _wait():
            await app.initialize()

            # First, consume any pending updates to get current offset
            try:
                updates = await app.bot.get_updates(timeout=0)
                for update in updates:
                    if update.update_id > self._last_update_id:
                        self._last_update_id = update.update_id
            except Exception:
                pass

            start_time = time.time()

            while True:
                if timeout > 0 and (time.time() - start_time) > timeout:
                    raise TimeoutError(f"No reply received within {timeout} seconds")

                try:
                    updates = await app.bot.get_updates(
                        offset=self._last_update_id + 1,
                        timeout=1,
                    )
                    for update in updates:
                        if update.update_id > self._last_update_id:
                            self._last_update_id = update.update_id

                        if update.message and update.message.text:
                            msg = update.message
                            if msg.chat.id == chat_id:
                                return msg.text
                except Exception as e:
                    logger.warning("get_updates_error", error=str(e))

                await asyncio.sleep(0.5)

        return asyncio.run(_wait())

    def wait_for_any_update(self, timeout: int, target: str | None = None) -> str | None:
        if target:
            _, chat_id = self.resolve_chat(target)
        else:
            # No explicit target: still restrict the ack to the default chat when
            # one is configured, but don't fail if the config is ambiguous.
            try:
                _, chat_id = self.resolve_chat(None)
            except TargetError:
                chat_id = None
        app = self._ensure_app()

        async def _wait():
            await app.initialize()

            # First, consume any pending updates to get current offset
            try:
                updates = await app.bot.get_updates(timeout=0)
                for update in updates:
                    if update.update_id > self._last_update_id:
                        self._last_update_id = update.update_id
            except Exception:
                pass

            start_time = time.time()

            while True:
                if timeout > 0 and (time.time() - start_time) > timeout:
                    return None

                try:
                    updates = await app.bot.get_updates(
                        offset=self._last_update_id + 1,
                        timeout=1,
                    )
                    for update in updates:
                        if update.update_id > self._last_update_id:
                            self._last_update_id = update.update_id

                        if update.message and update.message.text:
                            msg = update.message
                            if chat_id is None or msg.chat.id == chat_id:
                                return msg.text
                except Exception as e:
                    logger.warning("get_updates_error", error=str(e))

                await asyncio.sleep(0.5)

        return asyncio.run(_wait())

    def send_alert(
        self,
        text: str,
        wait_for_ack: bool = False,
        timeout: int = 300,
        parse_mode: str = "HTML",
        target: str | None = None,
    ) -> dict:
        target_id, _ = self.resolve_chat(target)
        message_id = self.send_message(text, parse_mode=parse_mode, target=target)

        if wait_for_ack:
            reply = self.wait_for_any_update(timeout, target=target)
            return {
                "message_id": message_id,
                "target": target_id,
                "acknowledged": reply is not None,
                "ack_message": reply,
            }
        return {
            "message_id": message_id,
            "target": target_id,
            "acknowledged": False,
            "ack_message": None,
        }

    def discover_chats(self, wait: float = 0) -> list[dict[str, Any]]:
        """Return the chats visible in the bot's pending updates.

        Telegram has no "list my chats" call: only chats that posted to the bot
        (channel posts where it is admin, new messages, membership changes) and
        whose updates are still pending can be reported. Updates are read
        without an offset so nothing is consumed; ``wait`` seconds of long
        polling let a channel post arrive while the command runs.
        """
        app = self._ensure_app()

        async def _discover():
            await app.initialize()
            found: dict[int, dict[str, Any]] = {}
            deadline = time.time() + max(float(wait or 0), 0.0)
            try:
                while True:
                    remaining = deadline - time.time()
                    updates = await app.bot.get_updates(
                        timeout=1 if remaining > 0 else 0
                    )
                    for update in updates:
                        chat = _chat_from_update(update)
                        if chat is None or chat.type not in CHAT_TYPES:
                            continue
                        found[chat.id] = {
                            "chat_id": chat.id,
                            "title": _chat_title(chat),
                            "username": getattr(chat, "username", "") or "",
                            "type": chat.type,
                        }
                    if time.time() >= deadline:
                        break
                    await asyncio.sleep(0.2)
            finally:
                await app.shutdown()
            return list(found.values())

        return asyncio.run(_discover())

    def resolve_chat_info(self, identifier: str) -> dict[str, Any]:
        """Resolve ``@username``, a t.me link or a numeric id via ``getChat``.

        Public channels can be resolved without any prior update. Private
        channels remain unreachable this way: Telegram only reveals them through
        an update (bot admin + a post) or a userbot.
        """
        ref = normalize_chat_ref(identifier)
        app = self._ensure_app()

        async def _resolve():
            await app.initialize()
            try:
                return await app.bot.get_chat(chat_id=ref)
            finally:
                await app.shutdown()

        try:
            chat = asyncio.run(_resolve())
        except TargetError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Could not resolve {identifier!r}: {exc}. Public channels and "
                "groups resolve by @username or t.me link. For a private channel, "
                "add the bot as an administrator, post once, then run "
                "'message targets discover --wait 120'."
            ) from exc

        return {
            "chat_id": chat.id,
            "title": _chat_title(chat),
            "username": getattr(chat, "username", "") or "",
            "type": chat.type,
        }

    def test_connection(self) -> bool:
        import sys

        if not self.bot_token:
            print("Error: No bot token configured", file=sys.stderr)
            return False

        app = self._ensure_app()

        async def _test():
            await app.initialize()
            try:
                me = await app.bot.get_me()
                print(f"Connection successful! Bot username: @{me.username}")
                return True
            except Exception as e:
                import traceback

                print(f"Connection failed: {e}", file=sys.stderr)
                print(f"Traceback:\n{traceback.format_exc()}", file=sys.stderr)
                return False
            finally:
                await app.shutdown()

        return asyncio.run(_test())


def _chat_from_update(update: Update):
    """Return the chat carried by an update, or None."""
    for field in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "my_chat_member",
        "chat_member",
    ):
        obj = getattr(update, field, None)
        chat = getattr(obj, "chat", None) if obj is not None else None
        if chat is not None:
            return chat
    return None


def _chat_title(chat) -> str:
    title = getattr(chat, "title", None)
    if title:
        return str(title)
    full_name = getattr(chat, "full_name", None)
    if full_name:
        return str(full_name)
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"
    return str(chat.id)
