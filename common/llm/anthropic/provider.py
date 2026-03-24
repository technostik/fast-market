from __future__ import annotations

import json
import sys

from common import structlog
from common.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LazyLLMProvider,
    ToolCall,
    _format_debug_request,
    _format_debug_response,
)

logger = structlog.get_logger(__name__)


class AnthropicProvider(LazyLLMProvider):
    name = "anthropic"

    def _initialize(self):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("pip install anthropic") from exc

        provider_config = (self.config.get("providers") or {}).get("anthropic", {})
        api_key_env = provider_config.get("api_key_env", "ANTHROPIC_API_KEY")
        api_key = __import__("os").environ.get(api_key_env)
        if not api_key:
            logger.warning(
                "anthropic_provider_not_initialized",
                reason=f"{api_key_env} environment variable not set",
            )
            self._provider = None
            return

        client = Anthropic(api_key=api_key)
        default_model = provider_config.get("default_model", "claude-sonnet-4-20250514")

        self._provider = _RealAnthropicProvider(
            client=client, default_model=default_model
        )
        logger.info("anthropic_provider_initialized", default_model=default_model)


def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-style tools to Anthropic format."""
    anthropic_tools = []
    for tool in tools:
        if "function" in tool:
            func = tool["function"]
            anthropic_tools.append(
                {
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
            )
        elif "name" in tool:
            anthropic_tools.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", {}),
                }
            )
    return anthropic_tools


class _RealAnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client, default_model: str):
        self.client = client
        self.default_model = default_model
        self._debug = False

    def set_debug(self, debug: bool) -> None:
        self._debug = debug

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model

        if self._debug:
            print("\n" + _format_debug_request(request), file=sys.stderr)

        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = _convert_tools_to_anthropic(request.tools)

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

        tool_calls = None
        if hasattr(response, "content") and response.content:
            first_block = response.content[0]
            if hasattr(first_block, "type") and first_block.type == "tool_use":
                tool_calls = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                id=block.id,
                                name=block.name,
                                arguments=block.input,
                            )
                        )
                content = ""
            elif hasattr(first_block, "text"):
                content = first_block.text
            else:
                content = str(first_block)
        else:
            content = ""

        result_response = LLMResponse(
            content=content,
            model=model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            metadata={"id": response.id},
            tool_calls=tool_calls,
        )

        if self._debug:
            print("\n" + _format_debug_response(result_response), file=sys.stderr)

        return result_response

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
        ]
