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


class XAIProvider(LazyLLMProvider):
    name = "xai"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._ensure_initialized()
        if self._provider is None:
            raise RuntimeError(
                f"XAI provider not initialized. "
                f"Check api_key configuration. "
                f"model: {getattr(self, 'default_model', 'not set')}"
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

        provider_config = (self.config.get("providers") or {}).get("xai", {})

        api_key_env = provider_config.get("api_key_env", "XAI_API_KEY")
        api_key = None
        if api_key_env and api_key_env.upper() not in ("", "NONE"):
            api_key = os.environ.get(api_key_env)
            if not api_key:
                logger.warning(
                    "xai_provider_not_initialized",
                    reason=f"{api_key_env} environment variable not set",
                )
                self._provider = None
                return

        default_model = provider_config.get("default_model", "")
        if not isinstance(default_model, str) or not default_model.strip():
            logger.warning(
                "xai_provider_not_initialized",
                reason="providers.xai.default_model must be configured",
            )
            self._provider = None
            return

        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

        self._provider = _RealXAIProvider(client=client, default_model=default_model)
        logger.info(
            "xai_provider_initialized",
            base_url="https://api.x.ai/v1",
            default_model=default_model,
        )


class _RealXAIProvider(LLMProvider):
    name = "xai"

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
        if request.timeout > 0:
            kwargs["timeout"] = request.timeout

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                if attempt == 2:
                    import warnings

                    warnings.warn(f"XAI API call failed after 3 retries: {exc}")
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

                    warnings.warn(f"XAI API call failed: {exc}")
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
                except json.JSONDecodeError:
                    args = {}
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
                "finish_reason": response.choices[0].finish_reason,
            },
            tool_calls=tool_calls,
        )

        if self._debug:
            print("\n" + _format_debug_response(result_response), file=sys.stderr)

        return result_response

    def list_models(self) -> list[str]:
        return [self.default_model]
