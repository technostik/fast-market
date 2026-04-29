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
            from dotenv import load_dotenv
            from pathlib import Path

            env_path = Path(__file__).parent.parent.parent.parent / ".env"
            load_dotenv(env_path)
        except ImportError:
            pass

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("pip install anthropic") from exc

        provider_config = (self.config.get("providers") or {}).get(self.provider_name or self.name, {})
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
        model = provider_config.get("model", "claude-sonnet-4-20250514")

        self._provider = _RealAnthropicProvider(
            client=client, model=model
        )
        logger.info("anthropic_provider_initialized", model=model)


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


def _convert_messages_to_anthropic(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style messages (with tool roles) to Anthropic format.

    Anthropic does not support a 'tool' role. Tool results must be sent as
    user messages with content blocks of type 'tool_result'.
    """
    result = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "tool":
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            }
            if result and result[-1]["role"] == "user":
                result[-1]["content"].append(tool_result_block)
            else:
                result.append({"role": "user", "content": [tool_result_block]})
        elif role == "assistant":
            if msg.get("tool_calls"):
                content_blocks = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    func_data = tc.get("function", {})
                    args = func_data.get("arguments", "{}")
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": func_data.get("name", ""),
                            "input": json.loads(args)
                            if isinstance(args, str)
                            else args,
                        }
                    )
                result.append({"role": "assistant", "content": content_blocks})
            else:
                result.append({"role": "assistant", "content": msg.get("content", "")})
        else:
            result.append({"role": role, "content": msg.get("content", "")})
    return result


class _RealAnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client, model: str):
        self.client = client
        self.model = model
        self._debug = False

    def set_debug(self, debug: bool) -> None:
        self._debug = debug

    def _complete_raw(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.model

        if self._debug:
            print("\n" + _format_debug_request(request), file=sys.stderr)

        if request.messages:
            messages = _convert_messages_to_anthropic(request.messages)
        else:
            messages = [{"role": "user", "content": request.prompt}]

        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = _convert_tools_to_anthropic(request.tools)
        if request.timeout > 0:
            kwargs["timeout"] = request.timeout

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
