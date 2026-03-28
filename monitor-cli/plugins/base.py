from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.models import ItemMetadata


@dataclass
class PluginManifest:
    name: str
    source_plugin_class: type
    cli_options: dict[str, list] = field(default_factory=dict)


class SourcePlugin(ABC):
    name: str

    def __init__(self, config: dict, source_config: dict):
        self.config = config
        self.source_config = source_config
        self.metadata = source_config.get("metadata", {})
        self.last_check = source_config.get("last_check")
        self.check_interval = source_config.get("check_interval")

    def _parse_interval(self, interval_str: str | int | None = None) -> int | None:
        """Parse interval string or integer to seconds.

        Args:
            interval_str: Interval string (e.g., '15m', '1h') or integer (e.g., 300).
                          Defaults to self.check_interval.

        Returns:
            Interval in seconds, or None if no interval configured (no cooldown).
        """
        interval = interval_str or self.check_interval
        if not interval:
            return None

        # Handle integer directly (e.g., 300 seconds)
        if isinstance(interval, int):
            return interval

        # Handle string format (e.g., '5m', '1h')
        from core.time_scheduler import parse_interval

        try:
            td = parse_interval(interval)
            return int(td.total_seconds())
        except (ValueError, TypeError):
            return None

    def _should_fetch(self, force: bool = False) -> bool:
        """Check if cooldown has elapsed since last fetch.

        Args:
            force: If True, bypass cooldown check.

        Returns:
            True if no cooldown is active (never checked, or enough time has passed).
            False if still in cooldown period.
        """
        if force:
            return True

        interval_seconds = self._parse_interval()
        if interval_seconds is None:
            return True

        if self.last_check is None:
            return False

        try:
            now = datetime.now(timezone.utc)

            if isinstance(self.last_check, str):
                last_check_dt = datetime.fromisoformat(self.last_check)
                if last_check_dt.tzinfo is None:
                    last_check_dt = last_check_dt.replace(tzinfo=timezone.utc)
            elif isinstance(self.last_check, datetime):
                last_check_dt = self.last_check
            else:
                return True

            elapsed = (now - last_check_dt).total_seconds()
            return elapsed >= interval_seconds
        except Exception:
            return True

    @abstractmethod
    async def fetch_new_items(
        self,
        last_item_id: str | None = None,
        limit: int = 50,
        last_fetched_at: datetime | None = None,
        force: bool = False,
    ) -> list[ItemMetadata]:
        pass

    @abstractmethod
    def validate_identifier(self, identifier: str) -> bool:
        pass

    @abstractmethod
    def get_identifier_display(self, identifier: str) -> str:
        pass
