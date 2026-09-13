"""Exercise AnthropicClassifier's response handling without network, via a stubbed SDK client."""
from types import SimpleNamespace

import pytest
from tenacity import wait_none

from src.agent.llm import AnthropicClassifier, LLMError
from src.agent.models import FeedbackItem


class _StubMessages:
    def __init__(self, content):
        self._content = content
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["tool_choice"]["name"] == "record_classification"
        return SimpleNamespace(content=self._content)


def _make(content):
    AnthropicClassifier.classify.retry.wait = wait_none()  # no back-off delays in tests
    clf = AnthropicClassifier.__new__(AnthropicClassifier)
    clf._client = SimpleNamespace(messages=_StubMessages(content))
    clf._model = "stub"
    return clf


ITEM = FeedbackItem(id="x", sender="a@b.c", subject="Export fails", body="500 on export")


def test_parses_tool_use_block():
    block = SimpleNamespace(type="tool_use", name="record_classification",
                            input={"type": "bug", "severity": "high", "area": "export", "title": "Export fails", "summary": "s", "confidence": 0.9})
    c = _make([SimpleNamespace(type="text", text="ok"), block]).classify(ITEM)
    assert c.type.value == "bug" and c.severity.value == "high"


def test_missing_tool_block_raises_after_retries():
    clf = _make([SimpleNamespace(type="text", text="no tool")])
    with pytest.raises(LLMError):
        clf.classify(ITEM)
    assert clf._client.messages.calls == 3


def test_invalid_schema_raises():
    block = SimpleNamespace(type="tool_use", name="record_classification", input={"type": "complaint", "title": "x"})
    with pytest.raises(LLMError):
        _make([block]).classify(ITEM)
