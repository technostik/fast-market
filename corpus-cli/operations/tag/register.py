from __future__ import annotations

import json
import re

from common.llm.base import LLMRequest

from operations.base import Operation, OperationManifest

_SYSTEM = (
    "You extract a list of 3-8 concise, lowercase, space-separated keyword tags "
    "that capture the topics of the document. Return a JSON array of strings, "
    "e.g. [\"machine learning\", \"python\"]. Nothing but the JSON array."
)


class TagOperation(Operation):
    name = "tag"
    field = "tags"
    requires = ("raw_text",)

    def run(self, doc: dict) -> list[str]:
        self.check_inputs(doc)
        response = self.llm().complete(
            LLMRequest(
                prompt=_clip(doc["raw_text"]),
                system=_SYSTEM,
                temperature=0.2,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
        )
        return _parse_tags(response.content)


def _parse_tags(content: str) -> list[str]:
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(t).strip().lower() for t in parsed if str(t).strip()]
    # Fallback: split on commas / newlines
    return [
        part.strip().strip('"').lower()
        for part in re.split(r"[,;\n]", content)
        if part.strip()
    ]


def _clip(text: str, limit: int = 20_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[...truncated]"


def register(config: dict) -> OperationManifest:
    return OperationManifest(
        name="tag",
        operation_class=TagOperation,
        field="tags",
        applies_to="all",
    )
