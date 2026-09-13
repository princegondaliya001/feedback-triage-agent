"""Feedback Triage Agent - command line entry point.

Examples:
  python main.py run --mock            # offline demo with fixture emails, no keys needed
  python main.py run                   # live: Gmail -> Claude -> GitHub -> Slack
  python main.py run --once            # process one inbox pass (same as run)
  python main.py run --watch 60        # keep polling every 60 seconds
  python main.py check                 # verify configuration and connectivity
  python main.py seed-inbox            # send the 10 sample emails to your own Gmail
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.agent.approval import auto_approve, terminal_approval
from src.agent.config import get_settings
from src.agent.integrations import MockInbox, MockIssueTracker, MockNotifier
from src.agent.llm import build_classifier
from src.agent.models import FeedbackItem
from src.agent.pipeline import PipelineConfig, TriagePipeline
from src.agent.tracing import Tracer

FIXTURES = Path(__file__).parent / "tests" / "fixtures" / "sample_feedback.json"


def load_fixture_items() -> list[FeedbackItem]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return [FeedbackItem(**{k: v for k, v in row.items() if k != "expected"}) for row in data]


def build_pipeline(args: argparse.Namespace) -> TriagePipeline:
    settings = get_settings()
    tracer = Tracer(settings.trace_dir)
    config = PipelineConfig(
        dedup_threshold=settings.dedup_threshold,
        require_approval_for=settings.require_approval_for,
        max_items=settings.gmail_max_results,
        repo_label=settings.github_repo or "mock/repo",
    )
    approve = auto_approve if args.auto_approve else terminal_approval

    if args.mock:
        classifier = build_classifier(mock=not args.real_llm, api_key=settings.anthropic_api_key, model=settings.anthropic_model)
        return TriagePipeline(
            inbox=MockInbox(load_fixture_items()),
            tracker=MockIssueTracker(),
            notifier=MockNotifier(),
            classifier=classifier,
            tracer=tracer,
            config=config,
            approve=approve,
        )

    missing = settings.validate_for_live()
    if missing:
        sys.exit("Missing configuration for live run:\n  - " + "\n  - ".join(missing) + "\nCopy .env.example to .env and fill it in, or use --mock.")

    from src.agent.integrations.gmail_client import GmailInbox
    from src.agent.integrations.github_client import GitHubIssues
    from src.agent.integrations.slack_client import SlackWebhook

    return TriagePipeline(
        inbox=GmailInbox(settings.gmail_credentials_file, settings.gmail_token_file, settings.gmail_label),
        tracker=GitHubIssues(settings.github_token, settings.github_repo),
        notifier=SlackWebhook(settings.slack_webhook_url),
        classifier=build_classifier(mock=False, api_key=settings.anthropic_api_key, model=settings.anthropic_model),
        tracer=tracer,
        config=config,
        approve=approve,
    )


def print_summary(pipeline: TriagePipeline, summary) -> None:
    print(f"\nRun {summary.run_id}  -  trace: {pipeline.tracer.path}")
    print("-" * 72)
    for r in summary.results:
        tag = r.action.value.replace("_", " ").upper()
        extra = f"#{r.issue_number}" if r.issue_number else (r.error or "")
        sev = f"[{r.classification.severity.value}]" if r.classification else ""
        print(f"  {tag:<24} {sev:<11} {r.subject[:45]:<45} {extra}")
    print("-" * 72)
    print("  counts :", summary.counts())
    print("  slack  :", "ok" if summary.slack_ok else f"FAILED - {summary.slack_error}")
    if isinstance(pipeline.notifier, MockNotifier) and pipeline.notifier.messages:
        print("\n--- Slack message (mock) ---\n" + pipeline.notifier.messages[-1])


def cmd_run(args: argparse.Namespace) -> int:
    while True:
        pipeline = build_pipeline(args)
        summary = pipeline.run()
        print_summary(pipeline, summary)
        if not args.watch:
            return 0 if summary.slack_ok else 1
        print(f"\nSleeping {args.watch}s ... (Ctrl+C to stop)")
        try:
            time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0


def cmd_check(args: argparse.Namespace) -> int:
    settings = get_settings()
    missing = settings.validate_for_live()
    print("Configuration:")
    print(f"  model        : {settings.anthropic_model}")
    print(f"  gmail label  : {settings.gmail_label}")
    print(f"  github repo  : {settings.github_repo or '(unset)'}")
    print(f"  approval for : {settings.require_approval_for}")
    if missing:
        print("\nMissing:\n  - " + "\n  - ".join(missing))
        return 1
    print("\nAll settings present. Testing connections ...")
    from src.agent.integrations.gmail_client import GmailInbox
    from src.agent.integrations.github_client import GitHubIssues
    from src.agent.integrations.slack_client import SlackWebhook

    ok = True
    for name, fn in (
        ("gmail", lambda: GmailInbox(settings.gmail_credentials_file, settings.gmail_token_file, settings.gmail_label)),
        ("github", lambda: GitHubIssues(settings.github_token, settings.github_repo).list_open_issues(1)),
        ("slack", lambda: SlackWebhook(settings.slack_webhook_url).post("Feedback Triage Agent connection check :white_check_mark:")),
    ):
        try:
            fn()
            print(f"  {name:<7}: ok")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  {name:<7}: FAILED - {type(exc).__name__}: {exc}")
    return 0 if ok else 1


def cmd_seed_inbox(args: argparse.Namespace) -> int:
    settings = get_settings()
    from src.agent.integrations.gmail_client import GmailInbox

    inbox = GmailInbox(settings.gmail_credentials_file, settings.gmail_token_file, settings.gmail_label)
    items = load_fixture_items()
    if args.limit:
        items = items[: args.limit]
    for item in items:
        msg_id = inbox.send_to_self(item.subject, item.body)
        print(f"  sent {msg_id}  {item.subject}")
    print(f"\nSent {len(items)} emails to yourself with label '{settings.gmail_label}'. Wait ~10s, then: python main.py run")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Feedback Triage Agent")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="process the inbox once (or keep polling with --watch)")
    run.add_argument("--mock", action="store_true", help="use fixture emails and in-memory GitHub/Slack (no keys)")
    run.add_argument("--real-llm", action="store_true", help="with --mock, still call the real Anthropic model")
    run.add_argument("--auto-approve", action="store_true", help="skip the terminal approval prompt for critical items")
    run.add_argument("--watch", type=int, default=0, metavar="SECONDS", help="poll interval; 0 = run once")
    run.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    check = sub.add_parser("check", help="validate .env and test each connection")
    check.set_defaults(func=cmd_check)

    seed = sub.add_parser("seed-inbox", help="send sample feedback emails to your own Gmail for the demo")
    seed.add_argument("--limit", type=int, default=0)
    seed.set_defaults(func=cmd_seed_inbox)

    return p.parse_args(argv)


if __name__ == "__main__":
    ns = parse_args()
    sys.exit(ns.func(ns))
