"""Named Telegram targets shared by message-cli and the publish plugins.

Targets live in the ``telegram.targets`` mapping of a profile's
``message/config.yaml``::

    telegram:
      bot_token: "..."
      allowed_chat_id: 255925597   # legacy fallback
      default_target: joriel
      targets:
        joriel:
          chat_id: 255925597
          label: Johann (DM)
          type: private

The mapping key is the id used on the command line (``--target joriel``).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Chat types the Telegram Bot API reports.
CHAT_TYPES = ("private", "group", "supergroup", "channel")

_TARGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_TG_LINK_PREFIXES = (
    "https://t.me/",
    "http://t.me/",
    "https://telegram.me/",
    "http://telegram.me/",
    "t.me/",
    "telegram.me/",
)


class TargetError(ValueError):
    """Raised when a Telegram target cannot be resolved or is invalid."""


def normalize_chat_ref(value: str) -> int | str:
    """Normalize a user-supplied chat reference for the Bot API.

    Accepts a numeric chat id (``-1001234``), an ``@username``, a bare
    username, or a ``t.me`` / ``telegram.me`` link. Returns an int for numeric
    ids and ``@username`` for the rest.
    """
    raw = (value or "").strip()
    if not raw:
        raise TargetError("Empty chat reference")

    if re.fullmatch(r"-?\d+", raw):
        return int(raw)

    lowered = raw.lower()
    for prefix in _TG_LINK_PREFIXES:
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    raw = raw.split("?", 1)[0].split("#", 1)[0].strip("/")
    if raw.lower().startswith("s/"):
        raw = raw[2:]
    if raw.startswith("+") or raw.lower().startswith("joinchat/"):
        raise TargetError(
            "Private invite links cannot be resolved by the Bot API. Add the bot "
            "as an administrator, post once in the channel, then run "
            "'message targets discover --wait 120'."
        )
    if raw.startswith("@"):
        raw = raw[1:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", raw):
        raise TargetError(
            f"Invalid chat reference {value!r}. Use a numeric chat id, an "
            "@username, or a t.me link."
        )
    return f"@{raw}"


def validate_target_id(target_id: str) -> str:
    """Return the normalized target id or raise ``TargetError``."""
    tid = (target_id or "").strip().lower()
    if not _TARGET_ID_RE.match(tid):
        raise TargetError(
            f"Invalid target id {target_id!r}: use lowercase letters, digits, '-' "
            "or '_', starting with a letter or digit (e.g. 'technostik')."
        )
    return tid


def slugify_target_id(value: str) -> str:
    """Turn a channel title or username into a target id (may return '')."""
    ascii_value = (
        unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")
    return slug[:48]


def unique_target_id(base: str, existing: dict[str, Any] | list[str]) -> str:
    """Return ``base`` or ``base_2``, ``base_3``… not present in ``existing``."""
    known = set(existing.keys() if isinstance(existing, dict) else existing)
    candidate = slugify_target_id(base) or "target"
    if candidate not in known:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in known:
        suffix += 1
    return f"{candidate}_{suffix}"


def normalize_targets(tg_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and normalize ``telegram.targets``.

    Returns ``{id: {chat_id: int, label: str, type: str}}``. An empty mapping is
    returned when only the legacy ``allowed_chat_id`` is configured.
    """
    raw = tg_cfg.get("targets") or {}
    if not isinstance(raw, dict):
        raise TargetError("telegram.targets must be a mapping of id -> {chat_id, label}")

    targets: dict[str, dict[str, Any]] = {}
    for raw_id, entry in raw.items():
        tid = validate_target_id(str(raw_id))
        if tid in targets:
            raise TargetError(f"Duplicate telegram target id after normalization: {tid!r}")
        if not isinstance(entry, dict):
            raise TargetError(
                f"telegram.targets.{raw_id} must be a mapping with a chat_id"
            )
        raw_chat_id = entry.get("chat_id")
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError) as exc:
            raise TargetError(
                f"telegram.targets.{raw_id}.chat_id must be an integer, "
                f"got {raw_chat_id!r}"
            ) from exc
        targets[tid] = {
            "chat_id": chat_id,
            "label": str(entry.get("label") or tid),
            "type": str(entry.get("type") or ""),
        }
    return targets


def _legacy_chat_id(tg_cfg: dict[str, Any]) -> str:
    """Return the legacy ``allowed_chat_id`` as a normalized chat id string."""
    value = tg_cfg.get("allowed_chat_id")
    return str(int(value)) if value is not None else ""


def resolve_target(
    tg_cfg: dict[str, Any], target: str | None = None
) -> tuple[str, int]:
    """Resolve ``target`` to ``(target_id, chat_id)``.

    Resolution order: explicit ``target`` (named id or raw numeric chat id),
    ``telegram.default_target``, a target matching the legacy
    ``allowed_chat_id``, a single configured target, then the legacy
    ``allowed_chat_id`` alone.
    """
    targets = normalize_targets(tg_cfg)

    if target is not None and str(target).strip():
        raw = str(target).strip()
        if raw.lower() in targets:
            tid = raw.lower()
            return tid, targets[tid]["chat_id"]
        try:
            return raw, int(raw)
        except ValueError:
            known = ", ".join(sorted(targets)) or "(none)"
            raise TargetError(
                f"Unknown telegram target {target!r}. Known targets: {known}. "
                "Add one with 'message targets add <id> --chat-id <chat_id>'."
            ) from None

    default = str(tg_cfg.get("default_target") or "").strip().lower()
    if default:
        if default not in targets:
            known = ", ".join(sorted(targets)) or "(none)"
            raise TargetError(
                f"telegram.default_target {default!r} is not a configured target. "
                f"Known targets: {known}."
            )
        return default, targets[default]["chat_id"]

    legacy = _legacy_chat_id(tg_cfg)
    if legacy:
        for tid, entry in targets.items():
            if str(entry["chat_id"]) == legacy:
                return tid, entry["chat_id"]
        return "allowed_chat_id", int(legacy)

    if len(targets) == 1:
        tid, entry = next(iter(targets.items()))
        return tid, entry["chat_id"]
    if targets:
        known = ", ".join(sorted(targets))
        raise TargetError(
            "No telegram.default_target configured and several targets exist "
            f"({known}). Add 'default_target' to the telegram config or pass --target."
        )
    raise TargetError(
        "No telegram target configured. Run "
        "'message targets add <id> --chat-id <chat_id>' or 'message targets discover'."
    )


def list_targets(tg_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return display rows for all configured targets (legacy id included)."""
    targets = normalize_targets(tg_cfg)
    default = str(tg_cfg.get("default_target") or "").strip().lower()
    legacy = _legacy_chat_id(tg_cfg)

    rows: list[dict[str, Any]] = []
    if not targets and legacy:
        rows.append(
            {
                "id": "allowed_chat_id",
                "chat_id": int(legacy),
                "label": "Legacy allowed_chat_id",
                "type": "",
                "is_default": True,
            }
        )
        return rows

    for tid, entry in targets.items():
        rows.append(
            {
                "id": tid,
                "chat_id": entry["chat_id"],
                "label": entry["label"],
                "type": entry["type"],
                "is_default": tid == default
                or (not default and legacy and str(entry["chat_id"]) == legacy),
            }
        )
    if legacy and not any(str(entry["chat_id"]) == legacy for entry in targets.values()):
        rows.append(
            {
                "id": "allowed_chat_id",
                "chat_id": int(legacy),
                "label": "Legacy allowed_chat_id",
                "type": "",
                "is_default": not default,
            }
        )
    return rows
