"""In-memory implementations used for tests, evaluation and offline demos."""

from __future__ import annotations

from ..models import FeedbackItem
from .base import ExistingIssue


class MockInbox:
    def __init__(self, items: list[FeedbackItem]) -> None:
        self._items = list(items)
        self.processed: list[str] = []

    def fetch_unprocessed(self, limit: int) -> list[FeedbackItem]:
        return [i for i in self._items if i.id not in self.processed][:limit]

    def mark_processed(self, item_id: str) -> None:
        self.processed.append(item_id)


class MockIssueTracker:
    def __init__(self, existing: list[ExistingIssue] | None = None, *, fail_on_create: bool = False) -> None:
        self.issues: list[ExistingIssue] = list(existing or [])
        self.comments: list[tuple[int, str]] = []
        self.bodies: dict[int, str] = {}
        self.labels: dict[int, list[str]] = {}
        self.fail_on_create = fail_on_create
        self._next = max((i.number for i in self.issues), default=0) + 1

    def list_open_issues(self, limit: int = 200) -> list[ExistingIssue]:
        return [i for i in self.issues if i.state == "open"][:limit]

    def create_issue(self, title: str, body: str, labels: list[str]) -> ExistingIssue:
        if self.fail_on_create:
            raise ConnectionError("simulated GitHub outage")
        issue = ExistingIssue(number=self._next, title=title, url=f"https://github.com/mock/repo/issues/{self._next}")
        self._next += 1
        self.issues.append(issue)
        self.bodies[issue.number] = body
        self.labels[issue.number] = labels
        return issue

    def add_comment(self, issue_number: int, body: str) -> None:
        if not any(i.number == issue_number for i in self.issues):
            raise ValueError(f"issue #{issue_number} does not exist")
        self.comments.append((issue_number, body))


class MockNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[str] = []
        self.fail = fail

    def post(self, text: str, blocks: list[dict] | None = None) -> None:
        if self.fail:
            raise ConnectionError("simulated Slack outage")
        self.messages.append(text)
