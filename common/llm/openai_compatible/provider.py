from __future__ import annotations

import json
import os
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
    format_message_history,
)

logger = structlog.get_logger(__name__)


class OpenAICompatibleProvider(LazyLLMProvider):
    name = "openai-compatible"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._ensure_initialized()
        if self._provider is None:
            raise RuntimeError(
                f"OpenAI-compatible provider not initialized. "
                f"Check base_url and API key configuration. "
                f"base_url: {getattr(self, 'base_url', 'not set')}, "
                f"model: {getattr(self, 'model', 'not set')}"
            )
        return self._provider.complete(request)

    def _initialize(self):
        try:
            from dotenv import load_dotenv
            from pathlib import Path

            env_path = Path(__file__).parent.parent.parent.parent / ".env"
            load_dotenv(env_path)
        except ImportError:
            pass

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai") from exc

        provider_config = (self.config.get("providers") or {}).get(
            self.provider_name or self.name, {}
        )
        base_url = provider_config.get("base_url", "")
        if not isinstance(base_url, str) or not base_url.strip():
            logger.warning(
                "openai_compatible_provider_not_initialized",
                reason="providers.openai-compatible.base_url must be configured",
            )
            self._provider = None
            return

        api_key_env = provider_config.get("api_key_env", "OPENAI_COMPATIBLE_API_KEY")
        api_key = None
        if api_key_env and api_key_env.upper() not in ("", "NONE"):
            api_key = os.environ.get(api_key_env)
            if not api_key:
                logger.warning(
                    "openai_compatible_provider_not_initialized",
                    reason=f"{api_key_env} environment variable not set",
                )
                self._provider = None
                return

        model = provider_config.get("model", "")
        if not isinstance(model, str) or not model.strip():
            logger.warning(
                "openai_compatible_provider_not_initialized",
                reason=f"providers.{self.provider_name or self.name}.model must be configured",
            )
            self._provider = None
            return

        flatten_messages = provider_config.get("flatten_messages", False)

        client = OpenAI(api_key=api_key or "", base_url=base_url)

        self._provider = _RealOpenAICompatibleProvider(
            client=client,
            base_url=base_url,
            model=model,
            flatten_messages=flatten_messages,
        )
        logger.info(
            "openai_compatible_provider_initialized",
            base_url=base_url,
            model=model,
        )


class _RealOpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(
        self, client, base_url: str, model: str, flatten_messages: bool = False
    ):
        self.client = client
        self.base_url = base_url
        self.model = model
        self.flatten_messages = flatten_messages
        self._debug = False

    def set_debug(self, debug: bool) -> None:
        self._debug = debug

    def _complete_raw(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.model

        if self._debug:
            print("\n" + _format_debug_request(request), file=sys.stderr)

        flatten = self.flatten_messages or request.flatten_messages

        if request.messages and flatten:
            prompt = format_message_history(request.messages)
            if request.system:
                prompt = f"[SYSTEM]\n{request.system}\n\n{prompt}"
            messages = [{"role": "user", "content": prompt}]
        elif request.messages:
            messages = list(request.messages)
            if request.system:
                messages.insert(0, {"role": "system", "content": request.system})
        else:
            messages = [{"role": "user", "content": request.prompt}]
            if request.system:
                messages.insert(0, {"role": "system", "content": request.system})

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"
        if request.response_format:
            kwargs["response_format"] = request.response_format
        if request.timeout > 0:
            kwargs["timeout"] = request.timeout

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                if attempt == 2:
                    import warnings

                    warnings.warn(
                        f"OpenAI-compatible API call failed after 3 retries: {exc}"
                    )
                    raise
                if not (
                    isinstance(exc, ConnectionError)
                    or (hasattr(exc, "status_code") and exc.status_code == 500)
                    or (
                        hasattr(exc, "response")
                        and hasattr(exc.response, "status_code")
                        and exc.response.status_code == 500
                    )
                ):
                    import warnings

                    warnings.warn(f"OpenAI-compatible API call failed: {exc}")
                    raise
                import time

                time.sleep(1)
        message = response.choices[0].message
        content = message.content or ""

        tool_calls = None
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Failed to parse tool call arguments: {tc.function.arguments[:200]}"
                    ) from exc
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        result_response = LLMResponse(
            content=content,
            model=model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            },
            metadata={
                "id": response.id,
                "base_url": self.base_url,
                "finish_reason": response.choices[0].finish_reason,
            },
            tool_calls=tool_calls,
        )

        if self._debug:
            print("\n" + _format_debug_response(result_response), file=sys.stderr)

        return result_response

    def list_models(self) -> list[str]:
        return [self.model]
