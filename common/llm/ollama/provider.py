from __future__ import annotations

import json
import sys
from urllib import error, request as urllib_request

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


class OllamaProvider(LazyLLMProvider):
    name = "ollama"

    def _initialize(self):
        provider_config = (self.config.get("providers") or {}).get("ollama", {})
        base_url = provider_config.get("base_url", "http://127.0.0.1:11434")
        model = provider_config.get("default_model", "")

        if not isinstance(base_url, str) or not base_url.strip():
            logger.warning(
                "ollama_provider_not_initialized",
                reason="providers.ollama.base_url must be configured",
            )
            self._provider = None
            return

        if not isinstance(model, str) or not model.strip():
            logger.warning(
                "ollama_provider_not_initialized",
                reason="providers.ollama.default_model must be configured",
            )
            self._provider = None
            return

        self._provider = _RealOllamaProvider(
            base_url=base_url.rstrip("/"), default_model=model
        )
        logger.info(
            "ollama_provider_initialized",
            base_url=base_url,
            default_model=model,
        )


def _convert_messages_to_ollama(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style messages to Ollama's native format.

    Ollama expects tool_calls[].function.arguments as a dict, not a JSON string.
    """
    result = []
    for msg in messages:
        converted = dict(msg)
        if "tool_calls" in converted:
            new_tool_calls = []
            for tc in converted["tool_calls"]:
                new_tc = dict(tc)
                func_data = dict(tc.get("function", {}))
                args = func_data.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                func_data["arguments"] = args
                new_tc["function"] = func_data
                new_tool_calls.append(new_tc)
            converted["tool_calls"] = new_tool_calls
        result.append(converted)
    return result


class _RealOllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, default_model: str):
        self.base_url = base_url
        self.default_model = default_model
        self._debug = False

    def set_debug(self, debug: bool) -> None:
        self._debug = debug

    def _complete_raw(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model

        if self._debug:
            print("\n" + _format_debug_request(request), file=sys.stderr)

        if request.messages:
            messages = _convert_messages_to_ollama(request.messages)
            if request.system:
                messages.insert(0, {"role": "system", "content": request.system})
        else:
            messages = [{"role": "user", "content": request.prompt}]
            if request.system:
                messages.insert(0, {"role": "system", "content": request.system})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.tools:
            payload["tools"] = request.tools

        if request.response_format:
            logger.debug(
                "ollama_ignores_response_format",
                requested=request.response_format,
            )

        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib_request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed with HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc.reason}") from exc
        except TimeoutError:
            raise RuntimeError(
                f"Ollama request timed out after 120s. Model may be loading. Check 'ollama list'."
            ) from None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON response from Ollama: {raw[:500]}"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                f"Unexpected response type from Ollama: {type(data)}. Response: {raw[:500]}"
            )

        message = data.get("message", {})
        if not isinstance(message, dict):
            raise RuntimeError(
                f"Unexpected message type from Ollama: {type(message)}. Response: {raw[:500]}"
            )

        data = json.loads(raw)
        message = data.get("message", {})
        content = message.get("content", "")

        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = []
            for tc in message["tool_calls"]:
                args = tc.get("function", {}).get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Failed to parse tool call arguments: {args[:200]}"
                        ) from exc
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=args,
                    )
                )

        response = LLMResponse(
            content=content,
            model=model,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            },
            metadata={
                "total_duration": data.get("total_duration"),
                "load_duration": data.get("load_duration"),
                "finish_reason": data.get("done"),
            },
            tool_calls=tool_calls,
        )

        if self._debug:
            print(f"\n[ollama] raw response:\n{raw[:2000]}", file=sys.stderr)
            print("\n" + _format_debug_response(response), file=sys.stderr)

        return response

    def list_models(self) -> list[str]:
        return [self.default_model]
