"""Typed data models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class FeedbackType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    SPAM = "spam"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class FeedbackItem:
    """A raw piece of feedback pulled from an inbox."""

    id: str
    sender: str
    subject: str
    body: str
    received_at: str = ""

    def preview(self, limit: int = 120) -> str:
        text = " ".join(self.body.split())
        return text if len(text) <= limit else text[:limit] + "..."


@dataclass
class Classification:
    """Structured output produced by the LLM for one feedback item."""

    type: FeedbackType
    severity: Severity
    area: str
    title: str
    summary: str
    confidence: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Classification":
        """Validate and coerce a raw dict (e.g. parsed JSON) into a Classification."""
        try:
            ftype = FeedbackType(str(data["type"]).lower())
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid feedback type: {data.get('type')!r}") from exc
        try:
            severity = Severity(str(data.get("severity", "none")).lower())
        except ValueError as exc:
            raise ValueError(f"invalid severity: {data.get('severity')!r}") from exc

        title = str(data.get("title", "")).strip()
        if not title:
            raise ValueError("title must not be empty")
        if len(title) > 100:
            title = title[:97] + "..."

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number") from exc
        confidence = max(0.0, min(1.0, confidence))

        return cls(
            type=ftype,
            severity=severity,
            area=str(data.get("area", "general")).strip().lower() or "general",
            title=title,
            summary=str(data.get("summary", "")).strip(),
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["severity"] = self.severity.value
        return d


class Action(str, Enum):
    CREATED_ISSUE = "created_issue"
    COMMENTED_DUPLICATE = "commented_duplicate"
    SKIPPED_SPAM = "skipped_spam"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    REJECTED_BY_HUMAN = "rejected_by_human"
    FAILED = "failed"


@dataclass
class TriageResult:
    """Outcome of processing one feedback item end-to-end."""

    item_id: str
    subject: str
    action: Action
    classification: Classification | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    error: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "subject": self.subject,
            "action": self.action.value,
            "classification": self.classification.to_dict() if self.classification else None,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "error": self.error,
            "steps": self.steps,
        }
