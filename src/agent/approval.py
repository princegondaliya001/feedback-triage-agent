"""Human-in-the-loop gate for high-impact actions."""

from __future__ import annotations

from typing import Callable

from .models import Classification, FeedbackItem

ApprovalFn = Callable[[FeedbackItem, Classification], bool]


def terminal_approval(item: FeedbackItem, classification: Classification) -> bool:
    print("\n" + "=" * 72)
    print(f"  APPROVAL REQUIRED - {classification.severity.value.upper()} {classification.type.value}")
    print("=" * 72)
    print(f"  From    : {item.sender}")
    print(f"  Subject : {item.subject}")
    print(f"  Title   : {classification.title}")
    print(f"  Summary : {classification.summary}")
    print("=" * 72)
    while True:
        answer = input("  Create this issue? [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def auto_approve(item: FeedbackItem, classification: Classification) -> bool:
    return True


def auto_reject(item: FeedbackItem, classification: Classification) -> bool:
    return False
