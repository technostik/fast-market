from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Prompt:
    """A reusable prompt template with placeholders."""

    name: str
    content: str
    description: str = ""
    model_provider: str = ""
    model_name: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class PromptExecution:
    """Record of a prompt execution."""

    prompt_name: str
    input_args: dict
    resolved_content: str
    output: str
    model_provider: str
    model_name: str
    timestamp: datetime
    metadata: dict = field(default_factory=dict)
