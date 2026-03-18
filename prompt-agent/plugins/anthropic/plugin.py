from __future__ import annotations

import os

from common import structlog
from plugins.base import LLMProvider, LLMRequest, LLMResponse, LazyLLMProvider

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
        api_key = os.environ.get(api_key_env)
        if not api_key:
            logger.warning(
                "anthropic_provider_not_initialized",
                reason=f"{api_key_env} environment variable not set"
            )
            self._provider = None
            return

        client = Anthropic(api_key=api_key)
        default_model = provider_config.get("default_model", "claude-sonnet-4-20250514")

        self._provider = _RealAnthropicProvider(
            client=client,
            default_model=default_model
        )
        logger.info("anthropic_provider_initialized", default_model=default_model)


class _RealAnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client, default_model: str):
        self.client = client
        self.default_model = default_model

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        logger.info(
            "anthropic_request",
            model=model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            prompt_chars=len(request.prompt),
        )

        kwargs = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system

        response = self.client.messages.create(**kwargs)
        content = response.content[0].text
        logger.info(
            "anthropic_response",
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            output_chars=len(content),
        )
        return LLMResponse(
            content=content,
            model=model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            metadata={"id": response.id},
        )

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250514",
        ]
