from __future__ import annotations

import asyncio
import time
import threading
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from common import structlog
from plugins.base import MessagePlugin

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class TelegramPlugin(MessagePlugin):
    name = "telegram"

    def __init__(self, config: dict):
        self.config = config
        tg_config = config.get("telegram", {})
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

    def send_message(self, text: str, parse_mode: str = "HTML") -> int:
        if not self.allowed_chat_id:
            raise RuntimeError(
                "No allowed_chat_id configured. Run 'message setup --plugin telegram' first."
            )

        app = self._ensure_app()

        async def _send():
            await app.initialize()
            try:
                message = await app.bot.send_message(
                    chat_id=self.allowed_chat_id,
                    text=text,
                    parse_mode=parse_mode,
                )
                return message.message_id
            finally:
                await app.shutdown()

        return asyncio.run(_send())

    def wait_for_reply(self, timeout: int) -> str:
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
                            if msg.chat.id == self.allowed_chat_id:
                                return msg.text
                except Exception as e:
                    logger.warning("get_updates_error", error=str(e))

                await asyncio.sleep(0.5)

        return asyncio.run(_wait())

    def wait_for_any_update(self, timeout: int) -> str | None:
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
                            if (
                                self.allowed_chat_id is None
                                or msg.chat.id == self.allowed_chat_id
                            ):
                                return msg.text
                except Exception as e:
                    logger.warning("get_updates_error", error=str(e))

                await asyncio.sleep(0.5)

        return asyncio.run(_wait())

    def send_alert(
        self, text: str, wait_for_ack: bool = False, timeout: int = 300
    ) -> dict:
        message_id = self.send_message(text)

        if wait_for_ack:
            reply = self.wait_for_any_update(timeout)
            return {
                "message_id": message_id,
                "acknowledged": reply is not None,
                "ack_message": reply,
            }
        return {
            "message_id": message_id,
            "acknowledged": False,
            "ack_message": None,
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
