from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PendingAsk:
    message_id: int
    chat_id: int
    message_text: str
    timestamp: float


@dataclass
class AlertResult:
    message_id: int
    chat_id: int
    acknowledged: bool = False
    ack_message: str | None = None


@dataclass
class AskResult:
    message_id: int
    chat_id: int
    response_text: str
    response_message_id: int


@dataclass
class TelegramConfig:
    bot_token: str | None = None
    allowed_chat_id: int | None = None
    default_timeout: int = 300
    default_wait_for_ack: bool = False
