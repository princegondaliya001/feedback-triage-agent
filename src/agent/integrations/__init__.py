"""External app integrations. Each real client has a mock twin with the same interface."""

from .base import InboxClient, IssueTracker, Notifier, ExistingIssue
from .mock import MockInbox, MockIssueTracker, MockNotifier

__all__ = [
    "InboxClient",
    "IssueTracker",
    "Notifier",
    "ExistingIssue",
    "MockInbox",
    "MockIssueTracker",
    "MockNotifier",
]
