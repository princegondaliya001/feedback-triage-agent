"""LLM-based feedback classification.

Two implementations share one interface:
  * AnthropicClassifier - real model via the Anthropic Messages API (tool use for
    guaranteed-schema JSON output)
  * MockClassifier      - deterministic keyword heuristics, used for offline tests,
    evaluation baselines and demos without an API key
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import Classification, FeedbackItem, FeedbackType, Severity

SYSTEM_PROMPT = """You are a triage assistant for a software product's customer feedback inbox.
Classify each email precisely. Rules:
- type: "bug" (something broken), "feature" (a request), "question" (needs an answer, nothing to build), "spam" (marketing, unrelated, nonsense).
- severity: "critical" only for data loss, security, payments failing, or the product being unusable for many users. "high" for a core flow broken for the reporter. "medium" for degraded but workable. "low" for cosmetic. Use "none" for questions and spam.
- area: one short lowercase word for the product area (e.g. auth, billing, export, ui, api, performance, mobile, general).
- title: an imperative, specific issue title under 80 characters, no email prefixes like "Re:".
- summary: 1-2 sentences, factual, including any reproduction steps or numbers mentioned.
- confidence: 0.0-1.0 how sure you are of the type and severity.
Never invent details that are not in the email."""

CLASSIFY_TOOL: dict[str, Any] = {
    "name": "record_classification",
    "description": "Record the structured triage classification for one feedback email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [t.value for t in FeedbackType]},
            "severity": {"type": "string", "enum": [s.value for s in Severity]},
            "area": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["type", "severity", "area", "title", "summary", "confidence"],
    },
}


class Classifier(Protocol):
    name: str

    def classify(self, item: FeedbackItem) -> Classification: ...


class LLMError(RuntimeError):
    """Raised when the model returns an unusable response after retries."""


# --------------------------------------------------------------------------- real
class AnthropicClassifier:
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for AnthropicClassifier")
        from anthropic import Anthropic  # imported lazily so mock mode needs no SDK

        self._client = Anthropic(api_key=api_key)
        self._model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((LLMError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    def classify(self, item: FeedbackItem) -> Classification:
        user_content = (
            f"From: {item.sender}\nSubject: {item.subject}\nReceived: {item.received_at}\n\n{item.body[:6000]}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": CLASSIFY_TOOL["name"]},
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == CLASSIFY_TOOL["name"]:
                try:
                    return Classification.from_dict(dict(block.input))
                except ValueError as exc:
                    raise LLMError(f"model returned invalid classification: {exc}") from exc
        raise LLMError("model response contained no tool_use block")


# --------------------------------------------------------------------------- mock
_BUG_WORDS = ("error", "crash", "broken", "fail", "bug", "not working", "doesn't work", "500", "exception", "stuck", "wrong", "lost", "can't", "cannot", "unable", "slow", "charged twice", "refund", "incorrect", "shown one day")
_FEATURE_WORDS = ("feature", "would be nice", "could you add", "please add", "suggest", "wish", "support for", "it would be great", "request")
_QUESTION_WORDS = ("how do i", "how can i", "is it possible", "where is", "what is", "question", "?", "does it")
_SPAM_WORDS = ("unsubscribe", "limited offer", "buy now", "casino", "crypto", "winner", "click here", "seo services", "guest post")
_CRITICAL_WORDS = ("data loss", "lost all", "security", "leak", "payment", "charged twice", "cannot log in", "can't log in", "everyone", "all users", "production down")
_LOW_WORDS = ("cosmetic", "typo", "minor", "confusing", "annoying but")
_HIGH_WORDS = ("crash", "cannot", "can't", "unable", "blocked", "500", "fails every")
_AREAS = {
    "auth": ("login", "log in", "password", "sign in", "2fa", "session"),
    "billing": ("invoice", "payment", "charged", "billing", "subscription", "refund"),
    "export": ("export", "csv", "pdf", "download"),
    "performance": ("slow", "timeout", "loading", "lag"),
    "mobile": ("ios", "android", "iphone", "mobile app"),
    "api": ("api", "webhook", "endpoint", "token"),
    "ui": ("layout", "dark mode", "font", "colour", "color", "alignment", "theme"),
}


class MockClassifier:
    """Deterministic keyword classifier. Good enough to exercise every code path."""

    name = "mock"

    def classify(self, item: FeedbackItem) -> Classification:
        text = f"{item.subject}\n{item.body}".lower()

        subject = item.subject.lower().strip()
        subject_is_question = subject.endswith("?") or subject.startswith(("how ", "what ", "where ", "is it ", "can i ", "does "))

        if any(w in text for w in _SPAM_WORDS):
            ftype, severity = FeedbackType.SPAM, Severity.NONE
        elif subject_is_question:
            ftype, severity = FeedbackType.QUESTION, Severity.NONE
        elif any(w in text for w in _BUG_WORDS):
            ftype = FeedbackType.BUG
            if any(w in text for w in _CRITICAL_WORDS):
                severity = Severity.CRITICAL
            elif any(w in text for w in _HIGH_WORDS):
                severity = Severity.HIGH
            elif any(w in text for w in _LOW_WORDS):
                severity = Severity.LOW
            else:
                severity = Severity.MEDIUM
        elif any(w in text for w in _FEATURE_WORDS):
            ftype, severity = FeedbackType.FEATURE, Severity.LOW
        elif any(w in text for w in _QUESTION_WORDS):
            ftype, severity = FeedbackType.QUESTION, Severity.NONE
        else:
            ftype, severity = FeedbackType.QUESTION, Severity.NONE

        area = next((name for name, words in _AREAS.items() if any(w in text for w in words)), "general")
        title = re.sub(r"^(re|fwd?|fw):\s*", "", item.subject, flags=re.I).strip() or "Untitled feedback"
        return Classification(
            type=ftype,
            severity=severity,
            area=area,
            title=title[:80],
            summary=item.preview(200),
            confidence=0.75,
        )


def build_classifier(*, mock: bool, api_key: str, model: str) -> Classifier:
    return MockClassifier() if mock else AnthropicClassifier(api_key=api_key, model=model)


def classification_to_json(c: Classification) -> str:
    return json.dumps(c.to_dict(), indent=2)
