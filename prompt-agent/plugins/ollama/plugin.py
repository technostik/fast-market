from __future__ import annotations

import json
from urllib import error, request as urllib_request

from common import structlog
from plugins.base import LLMProvider, LLMRequest, LLMResponse

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, config: dict):
        provider_config = (config.get("providers") or {}).get("ollama", {})
        base_url = provider_config.get("base_url", "http://127.0.0.1:11434")
        model = provider_config.get("default_model", "")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("providers.ollama.base_url must be configured")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("providers.ollama.default_model must be configured")
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        logger.info(
            "ollama_provider_initialized",
            base_url=self.base_url,
            default_model=self.default_model,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.default_model
        logger.info(
            "ollama_request",
            model=model,
            base_url=self.base_url,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            prompt_chars=len(request.prompt),
        )

        payload = {
            "model": model,
            "prompt": request.prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.system:
            payload["system"] = request.system

        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            f"{self.base_url}/api/generate",
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

        data = json.loads(raw)
        content = str(data.get("response", ""))
        logger.info(
            "ollama_response",
            model=model,
            output_chars=len(content),
            done=bool(data.get("done", False)),
        )
        return LLMResponse(
            content=content,
            model=model,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            },
            metadata={
                "total_duration": data.get("total_duration"),
                "load_duration": data.get("load_duration"),
            },
        )

    def list_models(self) -> list[str]:
        return [self.default_model]
