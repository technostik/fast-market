from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    """Request to an LLM provider."""

    prompt: str
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    system: str | None = None


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    usage: dict | None = None
    metadata: dict | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        raise NotImplementedError


class LazyLLMProvider(LLMProvider):
    """Base class for providers that need lazy initialization."""

    def __init__(self, config: dict):
        self.config = config
        self._initialized = False
        self._provider = None

    def _ensure_initialized(self):
        """Ensure the provider is initialized before use."""
        if not self._initialized:
            self._initialize()
            self._initialized = True

    def _initialize(self):
        """Actual initialization logic to be implemented by subclasses."""
        raise NotImplementedError

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._ensure_initialized()
        return self._provider.complete(request)

    def list_models(self) -> list[str]:
        self._ensure_initialized()
        return self._provider.list_models()


@dataclass
class PluginManifest:
    """Everything an LLM provider plugin contributes."""

    name: str
    provider_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
