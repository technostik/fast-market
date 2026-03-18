from __future__ import annotations

import os

from common import structlog
from plugins.base import LLMProvider, LLMRequest, LLMResponse, LazyLLMProvider

logger = structlog.get_logger(__name__)


class OpenAIProvider(LazyLLMProvider):
    name = "openai"

    def _initialize(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai") from exc

        provider_config = (self.config.get("providers") or {}).get("openai", {})
        api_key_env = provider_config.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            logger.warning(
                "openai_provider_not_initialized",
                reason=f"{api_key_env} environment variable not set"
            )
            self._provider = None
            return

        client = OpenAI(api_key=api_key)
        default_model = provider_config.get("default_model", "gpt-4")

        self._provider = _RealOpenAIProvider(
            client=client,
            default_model=default_model
        )
        logger.info("openai_provider_initialized", default_model=default_model)


class _RealOpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, client, default_model: str):
        self.client = client
        self.default_model = default_model

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        logger.info(
            "openai_request",
            model=model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            prompt_chars=len(request.prompt),
        )

        messages = [{"role": "user", "content": request.prompt}]
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        content = response.choices[0].message.content or ""
        logger.info(
            "openai_response",
            model=model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            output_chars=len(content),
        )
        return LLMResponse(
            content=content,
            model=model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            },
            metadata={"id": response.id},
        )

    def list_models(self) -> list[str]:
        return ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
