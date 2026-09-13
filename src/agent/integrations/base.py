"""Interfaces for the three external apps. Keeping them tiny makes mocking trivial."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import FeedbackItem


@dataclass
class ExistingIssue:
    number: int
    title: str
    url: str
    state: str = "open"


class InboxClient(Protocol):
    """Source of feedback (Gmail)."""

    def fetch_unprocessed(self, limit: int) -> list[FeedbackItem]: ...

    def mark_processed(self, item_id: str) -> None: ...


class IssueTracker(Protocol):
    """Where issues live (GitHub)."""

    def list_open_issues(self, limit: int = 200) -> list[ExistingIssue]: ...

    def create_issue(self, title: str, body: str, labels: list[str]) -> ExistingIssue: ...

    def add_comment(self, issue_number: int, body: str) -> None: ...


class Notifier(Protocol):
    """Where the team gets told (Slack)."""

    def post(self, text: str, blocks: list[dict] | None = None) -> None: ...
