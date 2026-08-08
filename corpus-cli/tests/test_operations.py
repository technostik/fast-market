from __future__ import annotations

import pytest

from common.llm.base import LLMRequest, LLMResponse
from core.sync_errors import MissingInputFieldError
from operations.base import OperationManifest
from operations.summarize.register import SummarizeOperation, register as summarize_register
from operations.tag.register import TagOperation, register as tag_register


class FakeLLM:
    def __init__(self, content: str):
        self._content = content

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self._content, model="fake")


@pytest.fixture
def config():
    return {}


def test_summarize_register_manifest(config):
    manifest = summarize_register(config)
    assert isinstance(manifest, OperationManifest)
    assert manifest.name == "summarize"
    assert manifest.field == "summary"
    assert manifest.applies_to == "all"


def test_tag_register_manifest(config):
    manifest = tag_register(config)
    assert isinstance(manifest, OperationManifest)
    assert manifest.name == "tag"
    assert manifest.field == "tags"


def test_summarize_returns_llm_output(config):
    op = SummarizeOperation(config)
    op.llm = lambda: FakeLLM("A concise summary.")
    doc = {"source_plugin": "obsidian", "source_id": "a.md", "raw_text": "# H\nbody" * 10}
    assert op.run(doc) == "A concise summary."


def test_summarize_missing_raw_text_raises(config):
    op = SummarizeOperation(config)
    with pytest.raises(MissingInputFieldError):
        op.run({"source_plugin": "obsidian", "source_id": "a.md"})


def test_tag_parses_json_array(config):
    op = TagOperation(config)
    op.llm = lambda: FakeLLM('["machine learning", "python"]')
    doc = {"source_plugin": "youtube", "source_id": "v1", "raw_text": "body"}
    assert op.run(doc) == ["machine learning", "python"]


def test_tag_parses_json_object_wrapped(config):
    op = TagOperation(config)
    op.llm = lambda: FakeLLM('{"tags": ["a", "b"]}')
    doc = {"source_plugin": "obsidian", "source_id": "a.md", "raw_text": "body"}
    assert op.run(doc) == ["a", "b"]


def test_tag_fallback_comma_split(config):
    op = TagOperation(config)
    op.llm = lambda: FakeLLM("alpha, beta, gamma")
    doc = {"source_plugin": "obsidian", "source_id": "a.md", "raw_text": "body"}
    assert op.run(doc) == ["alpha", "beta", "gamma"]
