from src.agent.approval import auto_reject
from src.agent.integrations import MockInbox, MockIssueTracker, MockNotifier
from src.agent.integrations.base import ExistingIssue
from src.agent.llm import MockClassifier
from src.agent.models import Action
from src.agent.pipeline import PipelineConfig, TriagePipeline


def make(items, tracer, *, tracker=None, notifier=None, config=None, approve=None):
    kwargs = dict(
        inbox=MockInbox(items),
        tracker=tracker or MockIssueTracker(),
        notifier=notifier or MockNotifier(),
        classifier=MockClassifier(),
        tracer=tracer,
        config=config or PipelineConfig(dedup_threshold=70),
    )
    if approve:
        kwargs["approve"] = approve
    return TriagePipeline(**kwargs)


def test_end_to_end_happy_path(items, tracer):
    p = make(items, tracer)
    s = p.run()
    counts = s.counts()
    assert counts[Action.CREATED_ISSUE.value] == 8
    assert counts[Action.COMMENTED_DUPLICATE.value] == 1   # m006 duplicates m001
    assert counts[Action.SKIPPED_SPAM.value] == 1          # m005
    assert Action.FAILED.value not in counts
    assert s.slack_ok and len(p.notifier.messages) == 1
    assert "8 new issue(s)" in p.notifier.messages[0]
    # every processed email is marked, spam included, nothing left behind
    assert len(p.inbox.processed) == 10


def test_duplicate_links_to_existing_issue(items, tracer):
    tracker = MockIssueTracker(existing=[ExistingIssue(42, "Cannot log in after password reset", "https://x/42")])
    p = make(items[:1], tracer, tracker=tracker)
    s = p.run()
    r = s.results[0]
    assert r.action is Action.COMMENTED_DUPLICATE and r.issue_number == 42
    assert tracker.comments and tracker.comments[0][0] == 42


def test_tracker_outage_does_not_lose_email(items, tracer):
    tracker = MockIssueTracker(fail_on_create=True)
    p = make(items[1:2], tracer, tracker=tracker)  # m002: high bug, no approval needed
    s = p.run()
    assert s.results[0].action is Action.FAILED
    assert "GitHub outage" in s.results[0].error
    assert p.inbox.processed == []                # email stays for the next run
    assert any(not e["ok"] for e in tracer.events)  # failure is in the trace


def test_slack_outage_is_reported_but_issues_still_created(items, tracer):
    p = make(items[1:3], tracer, notifier=MockNotifier(fail=True))
    s = p.run()
    assert not s.slack_ok and "Slack outage" in s.slack_error
    assert s.counts()[Action.CREATED_ISSUE.value] == 2


def test_human_rejection_blocks_critical_issue(items, tracer):
    p = make(items[:1], tracer, approve=auto_reject)  # m001 is critical
    s = p.run()
    assert s.results[0].action is Action.REJECTED_BY_HUMAN
    assert p.tracker.issues == []


def test_low_confidence_left_for_human(items, tracer):
    cfg = PipelineConfig(min_confidence=0.99)  # mock classifier reports 0.75
    p = make(items[1:2], tracer, config=cfg)
    s = p.run()
    assert s.results[0].action is Action.SKIPPED_LOW_CONFIDENCE
    assert p.inbox.processed == []


def test_trace_file_is_written(items, tracer):
    make(items[:2], tracer).run()
    lines = tracer.path.read_text().strip().splitlines()
    assert lines[0].startswith('{"ts"')
    assert any('"event": "llm.classify"' in l for l in lines)
    assert any('"event": "run.end"' in l for l in lines)
