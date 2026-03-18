from __future__ import annotations

import os

from common import structlog
from plugins.base import LLMProvider, LLMRequest, LLMResponse

logger = structlog.get_logger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, config: dict):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai") from exc

        provider_config = (config.get("providers") or {}).get("openai-compatible", {})
        base_url = provider_config.get("base_url", "")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("providers.openai-compatible.base_url must be configured")

        api_key_env = provider_config.get("api_key_env", "OPENAI_COMPATIBLE_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"{api_key_env} environment variable not set")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self.default_model = provider_config.get("default_model", "")
        if not isinstance(self.default_model, str) or not self.default_model.strip():
            raise ValueError("providers.openai-compatible.default_model must be configured")

        logger.info(
            "openai_compatible_provider_initialized",
            base_url=self.base_url,
            default_model=self.default_model,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        logger.info(
            "openai_compatible_request",
            model=model,
            base_url=self.base_url,
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
            "openai_compatible_response",
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
            metadata={"id": response.id, "base_url": self.base_url},
        )

    def list_models(self) -> list[str]:
        return [self.default_model]
