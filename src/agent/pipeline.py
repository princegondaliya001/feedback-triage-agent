"""The agent loop: inbox -> classify -> dedup -> act -> notify, with tracing throughout.

Design rules that matter for reliability:
  * One email failing never stops the run; it is recorded as FAILED and the loop continues.
  * The inbox item is only marked processed *after* the tracker action succeeds, so a
    GitHub outage leaves the email for the next run instead of losing it.
  * Slack failure is reported but does not undo any work (the issues are already filed).
  * Critical items pass through a human approval gate before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass

from .approval import ApprovalFn, auto_approve
from .dedup import find_duplicate
from .formatting import duplicate_comment, issue_body, slack_summary
from .integrations.base import InboxClient, IssueTracker, Notifier
from .llm import Classifier
from .models import Action, Classification, FeedbackItem, FeedbackType, TriageResult
from .tracing import Tracer


@dataclass
class PipelineConfig:
    dedup_threshold: int = 80
    min_confidence: float = 0.4
    require_approval_for: tuple[str, ...] = ("critical",)
    max_items: int = 20
    repo_label: str = "repo"


@dataclass
class RunSummary:
    run_id: str
    results: list[TriageResult]
    slack_ok: bool
    slack_error: str | None = None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.action.value] = out.get(r.action.value, 0) + 1
        return out


class TriagePipeline:
    def __init__(
        self,
        *,
        inbox: InboxClient,
        tracker: IssueTracker,
        notifier: Notifier,
        classifier: Classifier,
        tracer: Tracer,
        config: PipelineConfig | None = None,
        approve: ApprovalFn = auto_approve,
    ) -> None:
        self.inbox = inbox
        self.tracker = tracker
        self.notifier = notifier
        self.classifier = classifier
        self.tracer = tracer
        self.config = config or PipelineConfig()
        self.approve = approve

    # ------------------------------------------------------------------ run
    def run(self) -> RunSummary:
        with self.tracer.step("inbox.fetch", limit=self.config.max_items) as out:
            items = self.inbox.fetch_unprocessed(self.config.max_items)
            out["count"] = len(items)

        with self.tracer.step("tracker.list_open_issues") as out:
            existing = self.tracker.list_open_issues()
            out["count"] = len(existing)

        results: list[TriageResult] = []
        for item in items:
            result = self._process(item, existing)
            results.append(result)
            if result.action is Action.CREATED_ISSUE and result.issue_number is not None:
                # make the freshly created issue visible to dedup for the rest of this run
                from .integrations.base import ExistingIssue

                existing.append(ExistingIssue(result.issue_number, result.classification.title, result.issue_url or ""))

        slack_ok, slack_error = self._notify(results)
        summary = RunSummary(run_id=self.tracer.run_id, results=results, slack_ok=slack_ok, slack_error=slack_error)
        self.tracer.finish({"counts": summary.counts(), "slack_ok": slack_ok, "failures": len(self.tracer.failures())})
        return summary

    # ------------------------------------------------------------- one item
    def _process(self, item: FeedbackItem, existing) -> TriageResult:
        result = TriageResult(item_id=item.id, subject=item.subject, action=Action.FAILED)
        try:
            classification = self._classify(item)
            result.classification = classification

            if classification.type is FeedbackType.SPAM:
                result.action = Action.SKIPPED_SPAM
                self._mark(item)
                return result

            if classification.confidence < self.config.min_confidence:
                result.action = Action.SKIPPED_LOW_CONFIDENCE
                self.tracer.event("decision.low_confidence", {"confidence": classification.confidence}, item_id=item.id)
                # leave unmarked so a human can look at it in the inbox
                return result

            if classification.type is FeedbackType.QUESTION:
                # Questions still become issues (label: question) so support can answer them.
                pass

            duplicate, score = find_duplicate(classification.title, existing, self.config.dedup_threshold)
            self.tracer.event(
                "decision.dedup",
                {"score": score, "matched": duplicate.number if duplicate else None, "threshold": self.config.dedup_threshold},
                item_id=item.id,
            )

            if duplicate is not None:
                with self.tracer.step("tracker.add_comment", item_id=item.id, issue=duplicate.number):
                    self.tracker.add_comment(duplicate.number, duplicate_comment(item, classification, score))
                result.action = Action.COMMENTED_DUPLICATE
                result.issue_number, result.issue_url = duplicate.number, duplicate.url
                self._mark(item)
                return result

            if classification.severity.value in self.config.require_approval_for:
                approved = self.approve(item, classification)
                self.tracer.event("decision.human_approval", {"approved": approved}, item_id=item.id)
                if not approved:
                    result.action = Action.REJECTED_BY_HUMAN
                    self._mark(item)
                    return result

            labels = [classification.type.value]
            if classification.severity.value != "none":
                labels.append(classification.severity.value)
            with self.tracer.step("tracker.create_issue", item_id=item.id, title=classification.title, labels=labels) as out:
                issue = self.tracker.create_issue(classification.title, issue_body(item, classification), labels)
                out["issue_number"], out["url"] = issue.number, issue.url
            result.action = Action.CREATED_ISSUE
            result.issue_number, result.issue_url = issue.number, issue.url
            self._mark(item)
            return result

        except Exception as exc:  # noqa: BLE001 - isolate failures per item
            result.action = Action.FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            self.tracer.event("item.failed", {"error": result.error}, ok=False, item_id=item.id)
            return result

    def _classify(self, item: FeedbackItem) -> Classification:
        with self.tracer.step("llm.classify", item_id=item.id, classifier=self.classifier.name, subject=item.subject) as out:
            classification = self.classifier.classify(item)
            out.update(classification.to_dict())
        return classification

    def _mark(self, item: FeedbackItem) -> None:
        with self.tracer.step("inbox.mark_processed", item_id=item.id):
            self.inbox.mark_processed(item.id)

    def _notify(self, results: list[TriageResult]) -> tuple[bool, str | None]:
        if not results:
            return True, None
        text, blocks = slack_summary(results, self.tracer.run_id, self.config.repo_label)
        try:
            with self.tracer.step("notifier.post", items=len(results)):
                self.notifier.post(text, blocks)
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
