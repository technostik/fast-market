from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.sync_errors import MissingInputFieldError


@dataclass
class OperationManifest:
    """Everything an operation contributes to the system.

    Fields:
        name:                 Unique operation name (e.g. "summarize").
        operation_class:      The Operation subclass (not an instance).
        field:                Name of the soft field this operation fills.
        applies_to:           "all" or a source plugin name.
    """

    name: str
    operation_class: type
    field: str = ""
    applies_to: str = "all"


class Operation(ABC):
    """An LLM-backed operation that computes a value for one soft field.

    Subclasses declare:
        name:          Operation name (e.g. "summarize").
        field:         Soft field this operation fills (e.g. "summary").
        applies_to:    "all" or a source plugin name.
        requires:      Metadata/column fields the document must carry for the
                       operation to run. Absence raises MissingInputFieldError.
    """

    name: str = ""
    field: str = ""
    applies_to: str = "all"
    requires: tuple[str, ...] = ()

    def __init__(self, config: dict) -> None:
        self.config = config

    def check_inputs(self, doc: dict) -> None:
        """Fail loudly when a required input field is missing from the document."""
        missing = [k for k in self.requires if not doc.get(k)]
        if missing:
            raise MissingInputFieldError(
                f"Operation '{self.name}' requires field(s): {', '.join(missing)} "
                f"(missing on {doc.get('source_plugin')}/{doc.get('source_id')}). "
                "Run the producing operation or `corpus field set` first."
            )

    @abstractmethod
    def run(self, doc: dict) -> Any:
        """Compute the field value for a document dict (from the store).

        The document dict carries at least: handle, source_plugin, source_id,
        title, raw_text, url, updated_at, duration_seconds, privacy_status,
        metadata.
        """
        raise NotImplementedError

    def llm(self) -> Any:
        """Build the default LLM provider from config (lazy)."""
        from common.llm.registry import discover_providers, get_default_provider_name

        providers = discover_providers(self.config)
        return providers[get_default_provider_name(self.config)]
