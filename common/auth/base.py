from __future__ import annotations

from abc import ABC, abstractmethod


class AuthProvider(ABC):
    """Base class for OAuth/API authentication providers."""

    @abstractmethod
    def get_client(self):
        """Return authenticated API client."""
        raise NotImplementedError
