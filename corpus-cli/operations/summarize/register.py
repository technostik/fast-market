from __future__ import annotations

from common.llm.base import LLMRequest

from operations.base import Operation, OperationManifest

_SYSTEM = (
    "You summarize documents written in any language into a short, neutral "
    "English summary of 2-4 sentences. Return only the summary text."
)


class SummarizeOperation(Operation):
    name = "summarize"
    field = "summary"
    requires = ("raw_text",)

    def run(self, doc: dict) -> str:
        self.check_inputs(doc)
        response = self.llm().complete(
            LLMRequest(
                prompt=_clip(doc["raw_text"]),
                system=_SYSTEM,
                temperature=0.3,
                max_tokens=400,
            )
        )
        return response.content.strip()


def _clip(text: str, limit: int = 20_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[...truncated]"


def register(config: dict) -> OperationManifest:
    return OperationManifest(
        name="summarize",
        operation_class=SummarizeOperation,
        field="summary",
        applies_to="all",
    )
