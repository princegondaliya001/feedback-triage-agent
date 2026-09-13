"""Text rendering for GitHub issue bodies and Slack messages."""

from __future__ import annotations

from .models import Action, Classification, FeedbackItem, TriageResult

_EMOJI = {"critical": ":rotating_light:", "high": ":red_circle:", "medium": ":large_orange_circle:", "low": ":white_circle:", "none": ":white_circle:"}


def issue_body(item: FeedbackItem, c: Classification) -> str:
    return (
        f"## Summary\n{c.summary}\n\n"
        f"| Field | Value |\n|---|---|\n"
        f"| Type | {c.type.value} |\n"
        f"| Severity | {c.severity.value} |\n"
        f"| Area | {c.area} |\n"
        f"| Confidence | {c.confidence:.2f} |\n"
        f"| Reporter | {item.sender} |\n"
        f"| Received | {item.received_at or 'n/a'} |\n\n"
        f"## Original message\n> **{item.subject}**\n>\n"
        + "\n".join(f"> {line}" if line.strip() else ">" for line in item.body.strip().splitlines()[:60])
        + "\n\n<sub>Filed automatically by Feedback Triage Agent from email `" + item.id + "`.</sub>"
    )


def duplicate_comment(item: FeedbackItem, c: Classification, score: int) -> str:
    return (
        f"**Another report of this issue** (title similarity {score}%)\n\n"
        f"- From: {item.sender}\n- Subject: {item.subject}\n- Severity assessed: {c.severity.value}\n\n"
        f"> {item.preview(400)}\n\n<sub>Linked automatically by Feedback Triage Agent from email `{item.id}`.</sub>"
    )


def slack_summary(results: list[TriageResult], run_id: str, repo: str) -> tuple[str, list[dict]]:
    created = [r for r in results if r.action is Action.CREATED_ISSUE]
    dupes = [r for r in results if r.action is Action.COMMENTED_DUPLICATE]
    skipped = [r for r in results if r.action in {Action.SKIPPED_SPAM, Action.SKIPPED_LOW_CONFIDENCE, Action.REJECTED_BY_HUMAN}]
    failed = [r for r in results if r.action is Action.FAILED]

    headline = (
        f"Feedback triage run `{run_id}` - {len(results)} email(s): "
        f"{len(created)} new issue(s), {len(dupes)} duplicate(s), {len(skipped)} skipped, {len(failed)} failed"
    )
    lines: list[str] = []
    for r in created:
        c = r.classification
        lines.append(f"{_EMOJI[c.severity.value]} *{c.severity.value.upper()}* <{r.issue_url}|#{r.issue_number}> {c.title} _({c.area})_")
    for r in dupes:
        lines.append(f":repeat: duplicate of <{r.issue_url}|#{r.issue_number}> - {r.subject}")
    for r in skipped:
        lines.append(f":no_entry_sign: {r.action.value.replace('_', ' ')} - {r.subject}")
    for r in failed:
        lines.append(f":warning: FAILED - {r.subject} - {r.error}")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Feedback triage summary"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
    ]
    if lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Repo: `{repo}` - trace id `{run_id}`"}]})
    return headline + "\n" + "\n".join(lines), blocks
