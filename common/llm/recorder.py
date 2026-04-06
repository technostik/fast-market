"""LLM session recorder - wraps any LLM provider to record request/response pairs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.llm.base import LLMProvider, LLMRequest, LLMResponse, ToolCall


class RecordingProvider(LLMProvider):
    """Wraps an LLM provider to record all request/response pairs to a JSONL file."""

    name = "recording"

    def __init__(self, wrapped: LLMProvider, output_path: Path | str):
        self.wrapped = wrapped
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # Clear file
        self.output_path.write_text("")
        self._call_count = 0

    def _complete_raw(self, request: LLMRequest) -> LLMResponse:
        response = self.wrapped._complete_raw(request)
        self._record(request, response)
        return response

    def list_models(self) -> list[str]:
        return self.wrapped.list_models()

    def _record(self, request: LLMRequest, response: LLMResponse) -> None:
        self._call_count += 1
        record = {
            "call": self._call_count,
            "request": {
                "model": request.model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "system": request.system,
                "tools": request.tools,
                "timeout": request.timeout,
                "messages": request.messages,
                "prompt": request.prompt,
                "response_format": request.response_format,
            },
            "response": {
                "content": response.content,
                "model": response.model,
                "usage": response.usage,
                "metadata": response.metadata,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                    for tc in (response.tool_calls or [])
                ],
            },
        }
        with open(self.output_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def get_call_count(self) -> int:
        return self._call_count
