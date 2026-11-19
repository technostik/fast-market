from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.helpers import build_plugin, load_config, out
from common.core.paths import get_tool_config
from common.core.profile import ENV_VAR, ProfileError, validate_profile_name
from common.core.yaml_utils import dump_yaml
from common.message_targets import (
    CHAT_TYPES,
    TargetError,
    list_targets,
    normalize_targets,
    validate_target_id,
)
from core.targets import merge_discovered


@contextmanager
def _profile_scope(profile: str | None):
    """Temporarily select a profile without touching the active-profile pointer."""
    if not profile:
        yield
        return
    try:
        validate_profile_name(profile)
    except ProfileError as exc:
        raise click.BadParameter(str(exc), param_hint="--profile") from exc
    previous = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = profile
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = previous


def _config_path() -> Path:
    path = get_tool_config("message")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_file() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise click.ClickException(f"{path} must contain a YAML mapping")
    return data


def _save_file(config: dict) -> None:
    path = _config_path()
    path.write_text(dump_yaml(config, sort_keys=False), encoding="utf-8")


def _telegram(config: dict) -> dict:
    tg = config.setdefault("telegram", {})
    if not isinstance(tg, dict):
        raise click.ClickException("telegram config section must be a YAML mapping")
    return tg


def _targets_map(tg: dict) -> dict:
    raw = tg.get("targets") or {}
    if not isinstance(raw, dict):
        raise click.ClickException(
            "telegram.targets must be a mapping of id -> {chat_id, label}"
        )
    return dict(raw)


def _discover(plugin, wait: float = 0) -> list[dict]:
    discover = getattr(plugin, "discover_chats", None)
    if discover is None:
        raise click.ClickException(
            f"Plugin '{getattr(plugin, 'name', '?')}' does not support target discovery"
        )
    try:
        return discover(wait=wait)
    except Exception as exc:
        raise click.ClickException(f"Telegram discovery failed: {exc}") from exc


def _resolve_chats(plugin, refs: tuple[str, ...]) -> list[dict]:
    resolve = getattr(plugin, "resolve_chat_info", None)
    if resolve is None:
        raise click.ClickException(
            f"Plugin '{getattr(plugin, 'name', '?')}' cannot resolve chat references"
        )
    chats = []
    for ref in refs:
        try:
            chats.append(resolve(ref))
        except Exception as exc:
            raise click.ClickException(f"Could not resolve {ref!r}: {exc}") from exc
    return chats


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("targets")
    def targets_group():
        """Manage named Telegram targets (chat ids)."""
        pass

    @targets_group.command("list")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    def list_cmd(fmt):
        config = load_config()
        tg = config.get("telegram", {}) if isinstance(config, dict) else {}
        try:
            rows = list_targets(tg)
        except TargetError as exc:
            raise click.ClickException(str(exc)) from exc

        if fmt == "json":
            out({"targets": rows, "default": tg.get("default_target")}, fmt)
            return
        if not rows:
            click.echo("No targets configured.")
            return
        for row in rows:
            marker = " (default)" if row["is_default"] else ""
            label = f" — {row['label']}" if row["label"] != row["id"] else ""
            chat_type = f" [{row['type']}]" if row["type"] else ""
            click.echo(
                f"  {row['id']}{marker}: chat_id={row['chat_id']}{chat_type}{label}"
            )

    @targets_group.command("add")
    @click.argument("target_id")
    @click.option("--chat-id", "chat_id", type=int, default=None, help="Numeric Telegram chat id")
    @click.option(
        "--username",
        "-u",
        default=None,
        help="Public @username or t.me link; the numeric chat id is resolved automatically.",
    )
    @click.option("--label", default="", help="Human-readable label")
    @click.option("--type", "chat_type", type=click.Choice(CHAT_TYPES), default=None)
    @click.option(
        "--profile",
        "profile",
        default=None,
        metavar="NAME",
        help="Write to this profile's message config instead of the active profile.",
    )
    def add_cmd(target_id, chat_id, username, label, chat_type, profile):
        try:
            tid = validate_target_id(target_id)
        except TargetError as exc:
            raise click.ClickException(str(exc)) from exc

        if chat_id is None and not username:
            raise click.UsageError("Pass --chat-id <id> or --username @channel.")
        if chat_id is not None and username:
            raise click.UsageError("Pass either --chat-id or --username, not both.")

        with _profile_scope(profile):
            if username:
                plugin = build_plugin(load_config(), "telegram")
                try:
                    info = plugin.resolve_chat_info(username)
                except Exception as exc:
                    raise click.ClickException(str(exc)) from exc
                chat_id = int(info["chat_id"])
                label = label or str(info.get("title") or "")
                chat_type = chat_type or str(info.get("type") or "") or None

            config = _load_file()
            tg = _telegram(config)
            targets = _targets_map(tg)
            if tid in targets:
                raise click.ClickException(
                    f"Target '{tid}' already exists. Remove it first or use another id."
                )
            for other_id, entry in targets.items():
                if int(entry.get("chat_id", 0)) == chat_id:
                    raise click.ClickException(
                        f"chat_id {chat_id} is already configured as '{other_id}'."
                    )

            entry: dict = {"chat_id": chat_id}
            if label:
                entry["label"] = label
            if chat_type:
                entry["type"] = chat_type
            targets[tid] = entry
            tg["targets"] = targets
            if not tg.get("default_target") and tg.get("allowed_chat_id") is None:
                tg["default_target"] = tid
            _save_file(config)
            suffix = f" [{chat_type}]" if chat_type else ""
            click.echo(f"Target '{tid}' added (chat_id={chat_id}{suffix}).")

    @targets_group.command("remove")
    @click.argument("target_id")
    def remove_cmd(target_id):
        try:
            tid = validate_target_id(target_id)
        except TargetError as exc:
            raise click.ClickException(str(exc)) from exc

        config = _load_file()
        tg = _telegram(config)
        targets = _targets_map(tg)
        if tid not in targets:
            raise click.ClickException(f"Unknown target '{tid}'.")
        del targets[tid]
        tg["targets"] = targets
        if str(tg.get("default_target") or "") == tid:
            tg.pop("default_target", None)
        _save_file(config)
        click.echo(f"Target '{tid}' removed.")

    @targets_group.command("default")
    @click.argument("target_id")
    def default_cmd(target_id):
        try:
            tid = validate_target_id(target_id)
        except TargetError as exc:
            raise click.ClickException(str(exc)) from exc

        config = _load_file()
        tg = _telegram(config)
        if tid not in _targets_map(tg):
            raise click.ClickException(f"Unknown target '{tid}'.")
        tg["default_target"] = tid
        _save_file(config)
        click.echo(f"Default target set to '{tid}'.")

    @targets_group.command("discover")
    @click.option(
        "--chat",
        "-c",
        "chat_refs",
        multiple=True,
        help="Public @username or t.me link to resolve (repeatable).",
    )
    @click.option(
        "--wait",
        "wait",
        type=float,
        default=0,
        show_default=True,
        help="Seconds to listen for a new channel post (bot must be channel admin).",
    )
    @click.option("--dry-run", is_flag=True, help="Show what would be added without writing")
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    def discover_cmd(chat_refs, wait, dry_run, fmt):
        if chat_refs and wait > 0:
            raise click.UsageError("--chat and --wait cannot be combined.")

        config = load_config()
        plugin = build_plugin(config, "telegram")
        chats = (
            _resolve_chats(plugin, chat_refs)
            if chat_refs
            else _discover(plugin, wait)
        )
        tg = config.get("telegram", {}) if isinstance(config, dict) else {}
        try:
            existing = normalize_targets(tg)
        except TargetError as exc:
            raise click.ClickException(str(exc)) from exc

        merged, added, updated = merge_discovered(existing, chats)

        if not dry_run:
            raw = _load_file()
            raw_tg = _telegram(raw)
            current = _targets_map(raw_tg)
            for tid, entry in merged.items():
                current[tid] = {
                    "chat_id": entry["chat_id"],
                    "label": entry["label"],
                    "type": entry["type"],
                }
            raw_tg["targets"] = current
            if (
                not raw_tg.get("default_target")
                and raw_tg.get("allowed_chat_id") is None
                and len(current) == 1
            ):
                raw_tg["default_target"] = next(iter(current))
            _save_file(raw)

        payload = {
            "status": "dry-run" if dry_run else "success",
            "added": added,
            "updated": updated,
            "targets": list_targets(
                {
                    "targets": merged,
                    "default_target": tg.get("default_target"),
                    "allowed_chat_id": tg.get("allowed_chat_id"),
                }
            ),
        }
        if fmt == "json":
            out(payload, fmt)
            return

        if not chats:
            click.echo(
                "No chats found. Telegram only exposes chats through:\n"
                "  • a public channel/group by username or link:\n"
                "      message targets discover --chat @mychannel\n"
                "  • a new post in a channel where the bot is administrator:\n"
                "      message targets discover --wait 120\n"
                "  • the numeric id, added manually:\n"
                "      message targets add mychannel --chat-id -1001234567890\n"
                "Find the id by forwarding a channel post to @RawDataBot, or by "
                "opening the channel on web.telegram.org (the id is in the URL)."
            )
        if added:
            click.echo(("Would add: " if dry_run else "Added: ") + ", ".join(added))
        if updated:
            click.echo(
                ("Would update: " if dry_run else "Updated: ") + ", ".join(updated)
            )
        if chats and not added and not updated:
            click.echo("No new targets; all discovered chats were already configured.")

    return CommandManifest(name="targets", click_command=targets_group)
