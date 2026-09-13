"""Evaluate the agent against the labelled fixture set and write eval/results.md.

    python eval/run_eval.py            # mock classifier (offline)
    python eval/run_eval.py --real-llm # real Anthropic model (needs ANTHROPIC_API_KEY)

Measures classification accuracy (type, severity, area), duplicate detection, and
end-to-end action correctness, using the same pipeline code as production.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.config import get_settings  # noqa: E402
from src.agent.integrations import MockInbox, MockIssueTracker, MockNotifier  # noqa: E402
from src.agent.llm import build_classifier  # noqa: E402
from src.agent.models import Action, FeedbackItem  # noqa: E402
from src.agent.pipeline import PipelineConfig, TriagePipeline  # noqa: E402
from src.agent.tracing import Tracer  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sample_feedback.json"
OUTPUT = ROOT / "eval" / "results.md"


def expected_action(exp: dict) -> Action:
    if exp["type"] == "spam":
        return Action.SKIPPED_SPAM
    if exp.get("duplicate_of"):
        return Action.COMMENTED_DUPLICATE
    return Action.CREATED_ISSUE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-llm", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    rows = json.loads(FIXTURES.read_text(encoding="utf-8"))
    items = [FeedbackItem(**{k: v for k, v in r.items() if k != "expected"}) for r in rows]
    classifier = build_classifier(
        mock=not args.real_llm,
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        workspace_id=settings.anthropic_workspace_id,
    )

    tracer = Tracer(ROOT / "logs", run_id="eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    pipeline = TriagePipeline(
        inbox=MockInbox(items),
        tracker=MockIssueTracker(),
        notifier=MockNotifier(),
        classifier=classifier,
        tracer=tracer,
        config=PipelineConfig(dedup_threshold=settings.dedup_threshold),
    )
    summary = pipeline.run()
    by_id = {r.item_id: r for r in summary.results}

    lines = [
        "# Evaluation results",
        "",
        f"- Classifier: `{classifier.name}`" + (f" (`{settings.anthropic_model}`)" if args.real_llm else ""),
        f"- Run id: `{tracer.run_id}`  -  trace: `{tracer.path.name}`",
        f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "| # | Subject | Exp. type | Got | Exp. sev | Got | Exp. area | Got | Exp. action | Got | OK |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    hits = {"type": 0, "severity": 0, "area": 0, "action": 0}
    for row in rows:
        exp, r = row["expected"], by_id[row["id"]]
        c = r.classification
        got_type = c.type.value if c else "-"
        got_sev = c.severity.value if c else "-"
        got_area = c.area if c else "-"
        exp_act = expected_action(exp)
        ok_type, ok_sev, ok_area, ok_act = got_type == exp["type"], got_sev == exp["severity"], got_area == exp["area"], r.action is exp_act
        for key, ok in zip(hits, (ok_type, ok_sev, ok_area, ok_act)):
            hits[key] += int(ok)
        all_ok = ok_type and ok_sev and ok_area and ok_act
        lines.append(
            f"| {row['id']} | {row['subject'][:38]} | {exp['type']} | {got_type} | {exp['severity']} | {got_sev} | "
            f"{exp['area']} | {got_area} | {exp_act.value} | {r.action.value} | {'✅' if all_ok else '❌'} |"
        )

    n = len(rows)
    lines += [
        "",
        "## Scores",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Type accuracy | {hits['type']}/{n} ({100 * hits['type'] // n}%) |",
        f"| Severity accuracy | {hits['severity']}/{n} ({100 * hits['severity'] // n}%) |",
        f"| Area accuracy | {hits['area']}/{n} ({100 * hits['area'] // n}%) |",
        f"| End-to-end action correct | {hits['action']}/{n} ({100 * hits['action'] // n}%) |",
        f"| Pipeline failures | {summary.counts().get('failed', 0)} |",
        f"| Slack notification | {'ok' if summary.slack_ok else 'FAILED'} |",
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWritten to {OUTPUT}")
    return 0 if hits["action"] == n else 1


if __name__ == "__main__":
    sys.exit(main())
