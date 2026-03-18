from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from common import structlog

logger = structlog.get_logger(__name__)


class QuotaState(BaseModel):
    usage: int = 0
    limit: int = 10000

    @property
    def usage_percentage(self) -> float:
        if self.limit <= 0:
            return 0.0
        return round((self.usage / self.limit) * 100, 2)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.usage)

    @property
    def remaining_percentage(self) -> float:
        return round(100 - self.usage_percentage, 2)


class QuotaTracker:
    """Track YouTube API quota usage."""

    def __init__(self, limit: int = 10000):
        self.limit = limit
        self._usage = 0

    def track(self, units: int) -> None:
        """Add quota units to the counter."""
        self._usage += units
        logger.debug("quota_tracked", units=units, total=self._usage, limit=self.limit)

    def reset(self) -> None:
        """Reset the quota counter."""
        self._usage = 0
        logger.debug("quota_reset")

    def get_usage(self) -> int:
        """Get current quota usage."""
        return self._usage

    def get_state(self) -> QuotaState:
        """Get full quota state."""
        return QuotaState(usage=self._usage, limit=self.limit)

    def set_usage(self, usage: int) -> None:
        """Set quota usage to a specific value."""
        self._usage = usage
        logger.debug("quota_set", usage=usage)

    def check_available(self, units: int = 0) -> bool:
        """Check if quota is available for the given units."""
        return (self._usage + units) < self.limit
