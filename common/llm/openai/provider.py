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
)

logger = structlog.get_logger(__name__)


class OpenAIProvider(LazyLLMProvider):
    name = "openai"

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

        provider_config = (self.config.get("providers") or {}).get(self.provider_name or self.name, {})
        api_key_env = provider_config.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            logger.warning(
                "openai_provider_not_initialized",
                reason=f"{api_key_env} environment variable not set",
            )
            self._provider = None
            return

        client = OpenAI(api_key=api_key)
        model = provider_config.get("model", "gpt-4")

        self._provider = _RealOpenAIProvider(client=client, model=model)
        logger.info("openai_provider_initialized", model=model)


class _RealOpenAIProvider(LLMProvider):
    name = "openai"

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

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                if attempt == 2:
                    import warnings

                    warnings.warn(f"OpenAI API call failed after 3 retries: {exc}")
                    break
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

                    warnings.warn(f"OpenAI API call failed: {exc}")
                    break
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
            metadata={"id": response.id},
            tool_calls=tool_calls,
        )

        if self._debug:
            print("\n" + _format_debug_response(result_response), file=sys.stderr)

        return result_response

    def list_models(self) -> list[str]:
        return ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
