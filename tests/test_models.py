import pytest

from src.agent.models import Classification, FeedbackType, Severity


def test_from_dict_valid():
    c = Classification.from_dict({"type": "BUG", "severity": "high", "area": " Auth ", "title": "Login fails", "summary": "x", "confidence": "0.9"})
    assert c.type is FeedbackType.BUG
    assert c.severity is Severity.HIGH
    assert c.area == "auth"
    assert c.confidence == 0.9


def test_from_dict_rejects_bad_type():
    with pytest.raises(ValueError):
        Classification.from_dict({"type": "complaint", "severity": "low", "title": "x"})


def test_from_dict_rejects_empty_title():
    with pytest.raises(ValueError):
        Classification.from_dict({"type": "bug", "severity": "low", "title": "   "})


def test_confidence_is_clamped_and_title_truncated():
    c = Classification.from_dict({"type": "bug", "severity": "low", "title": "a" * 150, "confidence": 7})
    assert c.confidence == 1.0
    assert len(c.title) == 100 and c.title.endswith("...")
