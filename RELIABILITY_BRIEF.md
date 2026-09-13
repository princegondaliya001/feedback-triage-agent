# System & Reliability Brief — Feedback Triage Agent

**Problem.** Product feedback arrives by email, gets read by whoever is least busy, and is either
forgotten or filed as a duplicate. Engineering sees noise; customers see silence.

**Agent.** One multi-step agent that reads labelled emails from **Gmail**, classifies them with
**Claude**, files or links issues in **GitHub**, and reports to **Slack** — with a human gate on
critical items and a complete trace of every decision.

## 1. System design

| Step | Tool | What happens | Failure handling |
|---|---|---|---|
| Fetch | Gmail API | Pull emails with label `feedback` and without `triaged` | 3 retries, exp. back-off; failure aborts run before any writes |
| Classify | Claude (tool use) | Forced JSON via `record_classification` tool schema; validated again in `Classification.from_dict` | Invalid/missing tool output → `LLMError` → retry (3×); still failing → item marked FAILED |
| Filter | code | Spam is skipped and marked; confidence < 0.4 is left in the inbox for a human | Deterministic |
| Dedup | rapidfuzz | Normalised title (prefix/stopword removal, light stemming) vs open issues, `token_set_ratio ≥ 80` | No match → create; match → comment. Issues created earlier in the same run are included |
| Approve | terminal | `critical` items require an explicit `y` before any write | Rejection is recorded and the email is marked so it is not re-asked |
| Act | GitHub API | Create labelled issue (labels auto-created) or add "+1 report" comment | 3 retries; failure → item FAILED, email **not** marked, retried next run |
| Mark | Gmail API | Add `triaged`, remove `UNREAD` — only after the write succeeded | Failure → item FAILED (issue exists; next run will dedup it, not duplicate it) |
| Notify | Slack webhook | One digest per run with severity, links, skips, failures | Failure reported in exit code and trace; never rolls back work |
| Trace | JSONL | Every step: inputs, outputs, ms, ok/error, item id | Written incrementally so a crash mid-run still leaves evidence |

Idempotency: the `triaged` label plus duplicate detection means re-running the agent on the same
inbox is safe — it will not file the same issue twice.

## 2. How we know it works

**Unit + scenario tests (19, all passing — `python -m pytest -q`)**

| Scenario | Assertion |
|---|---|
| Happy path, 10 emails | 8 issues, 1 duplicate comment, 1 spam skipped, 0 failures, 1 Slack post, all 10 marked |
| Pre-existing similar issue | Comment added to #42, no new issue |
| GitHub outage during create | Item FAILED, email **not** marked, failure present in trace |
| Slack outage | Issues still created, run reports `slack_ok=False` |
| Human rejects critical item | No issue written, action `rejected_by_human` |
| Low model confidence | Item left in inbox, action `skipped_low_confidence` |
| Schema validation | Bad type / empty title rejected, confidence clamped, title capped |
| Dedup | Near-duplicates matched, unrelated titles not matched, empty list safe |

**Labelled evaluation (`python eval/run_eval.py`, see `eval/results.md`)**

10 realistic emails with ground-truth type / severity / area / expected action, run through the
*same* pipeline code as production with in-memory GitHub and Slack. Reported: type accuracy,
severity accuracy, area accuracy, end-to-end action correctness, pipeline failures.
`--real-llm` runs the identical harness against Claude so model quality can be measured and
regressions caught before deployment.

**Evaluation-driven prompt iteration.** First live run (Claude): type 10/10, action 10/10, severity 5/10. Trace review showed two systematic causes — feature requests received none, and billing errors / team-wide lockouts were rated high. One prompt revision raised severity to 8/10 with no code change; the two remaining misses are one level apart and area: workspace vs general is the model being more specific than the label. Both tables are in `eval/results.md`.

**Live trace.** Each run writes `logs/trace-<run-id>.jsonl`; the Slack digest carries the run id so
any issue can be traced back to the exact model output and tool calls that produced it.

## 3. Known limitations & next steps

- Dedup is title-based; semantic (embedding) matching would catch differently-worded duplicates.
- Approval is a terminal prompt; a Slack interactive button would let a reviewer approve remotely.
- Polling, not push — Gmail push notifications (Pub/Sub) would cut latency to seconds.
- One inbox, one repo; routing by `area` to multiple repos is a config change away.
