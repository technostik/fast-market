from __future__ import annotations

import json as _json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool/function call from the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass
class LLMRequest:
    """Request to an LLM provider."""

    prompt: str
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048
    system: str | None = None
    tools: list[dict] | None = None


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    usage: dict | None = None
    metadata: dict | None = None
    tool_calls: list[ToolCall] | None = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        raise NotImplementedError

    def set_debug(self, debug: bool) -> None:
        """Enable or disable debug logging for this provider."""
        pass


class LazyLLMProvider(LLMProvider):
    """Base class for providers that need lazy initialization."""

    def __init__(self, config: dict):
        self.config = config
        self._initialized = False
        self._provider: LLMProvider | None = None
        self._debug = False

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

    def set_debug(self, debug: bool) -> None:
        self._debug = debug
        if self._initialized and self._provider:
            self._provider.set_debug(debug)


def _format_debug_request(request: LLMRequest) -> str:
    """Format debug info for a request."""
    lines = [
        "=" * 60,
        ">>> REQUEST TO LLM",
        "=" * 60,
        f"Model: {request.model or '(default)'}",
        f"Max tokens: {request.max_tokens}",
        f"Temperature: {request.temperature}",
        f"Has tools: {bool(request.tools)}",
    ]
    if request.tools:
        lines.append("\n--- TOOLS ---")
        lines.append(_json.dumps(request.tools, indent=2))
    lines.append("\n--- SYSTEM PROMPT (first 300 chars) ---")
    if request.system:
        lines.append(
            request.system[:300] + ("..." if len(request.system) > 300 else "")
        )
    else:
        lines.append("(none)")
    lines.append("\n--- USER MESSAGE (first 500 chars) ---")
    lines.append(request.prompt[:500] + ("..." if len(request.prompt) > 500 else ""))
    lines.append("=" * 60)
    return "\n".join(lines)


def _format_debug_response(response: LLMResponse) -> str:
    """Format debug info for a response."""
    lines = [
        "=" * 60,
        ">>> RESPONSE FROM LLM",
        "=" * 60,
        f"Model: {response.model}",
    ]
    if response.usage:
        lines.append(f"Usage: {response.usage}")
    lines.append(f"Has tool_calls: {bool(response.tool_calls)}")
    if response.tool_calls:
        lines.append("\n--- TOOL CALLS ---")
        for tc in response.tool_calls:
            lines.append(f"  - ID: {tc.id}")
            lines.append(f"    Name: {tc.name}")
            lines.append(f"    Arguments: {tc.arguments}")
    if response.metadata:
        lines.append(f"\nMetadata: {_json.dumps(response.metadata, indent=2)[:300]}")
    lines.append(f"\n--- CONTENT ({len(response.content)} chars) ---")
    lines.append(
        response.content[:500] + ("..." if len(response.content) > 500 else "")
    )
    lines.append("=" * 60)
    return "\n".join(lines)


@dataclass
class PluginManifest:
    """Everything an LLM provider plugin contributes."""

    name: str
    provider_class: type
    cli_options: dict[str, list] = field(default_factory=dict)
    api_router: Any | None = None
