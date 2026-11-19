"""Merge discovered Telegram chats into the named-target mapping."""

from __future__ import annotations

from typing import Any

from common.message_targets import slugify_target_id, unique_target_id


def merge_discovered(
    existing: dict[str, dict[str, Any]], chats: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    """Merge chats seen by the bot into ``existing`` targets.

    ``chats`` entries carry ``chat_id``, ``title``, ``username`` and ``type``
    (see ``TelegramPlugin.discover_chats``). Matching is done on ``chat_id`` so
    a channel is updated rather than duplicated when it is discovered again.

    Returns ``(merged, added_ids, updated_ids)``.
    """
    merged = {tid: dict(entry) for tid, entry in existing.items()}
    by_chat = {int(entry["chat_id"]): tid for tid, entry in merged.items()}
    added: list[str] = []
    updated: list[str] = []

    for chat in chats:
        chat_id = int(chat["chat_id"])
        title = str(chat.get("title") or "").strip()
        chat_type = str(chat.get("type") or "").strip()

        tid = by_chat.get(chat_id)
        if tid is not None:
            entry = merged[tid]
            if title:
                entry["label"] = title
            if chat_type:
                entry["type"] = chat_type
            updated.append(tid)
            continue

        base = (
            slugify_target_id(str(chat.get("username") or ""))
            or slugify_target_id(title)
            or f"chat_{abs(chat_id)}"
        )
        tid = unique_target_id(base, merged)
        merged[tid] = {
            "chat_id": chat_id,
            "label": title or tid,
            "type": chat_type,
        }
        by_chat[chat_id] = tid
        added.append(tid)

    return merged, added, updated
