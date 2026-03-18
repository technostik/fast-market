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


@dataclass
class PluginManifest:
    """Everything an LLM provider plugin contributes."""

    name: str
    provider_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
