# Feedback Triage Agent

A multi-step AI agent that turns a messy customer-feedback inbox into clean, de-duplicated,
prioritised engineering work — automatically, with a human gate on high-impact actions and a
full trace of every decision.

**Connected apps:** Gmail (read + label) → Claude (classify) → GitHub Issues (create / link) → Slack (notify)

```
 ┌────────┐   fetch     ┌──────────────┐  classify  ┌──────────────┐
 │ Gmail  │ ──────────▶ │   Agent loop │ ─────────▶ │ Claude (LLM) │
 │ label: │             │              │ ◀───────── │ tool-use JSON│
 │feedback│ ◀────────── │  dedup       │            └──────────────┘
 └────────┘  mark done  │  approval    │
                        │  act         │ ──────────▶ ┌──────────────┐
                        │  notify      │  create /   │ GitHub Issues│
                        │  trace       │  comment    └──────────────┘
                        └──────┬───────┘
                               │ summary        ┌──────────────┐
                               └──────────────▶ │    Slack     │
                                                └──────────────┘
                               │ every step      logs/trace-<run>.jsonl
```

## What it does

For every unprocessed email carrying the `feedback` label, the agent:

1. **Classifies** it with Claude via a strict tool-use schema: type (bug / feature / question / spam),
   severity, product area, an imperative issue title, a factual summary and a confidence score.
2. **Skips spam** and leaves **low-confidence** items in the inbox for a human.
3. **Detects duplicates** against open GitHub issues (normalised fuzzy title match) and, if found,
   adds a "+1 report" comment instead of opening a new issue.
4. **Asks for human approval** in the terminal before filing anything classified as *critical*.
5. **Creates a labelled GitHub issue** with the structured fields and the original message.
6. **Marks the email processed** (label `triaged`) — only after the write succeeded.
7. **Posts a Slack digest** of the run with links to every issue.
8. **Traces every step** (inputs, outputs, timing, success/failure) to a JSONL file.

## Quick start (offline demo, no keys needed)

```bash
git clone <your-repo-url>
cd feedback-triage-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python main.py run --mock --auto-approve   # 10 sample emails -> in-memory GitHub/Slack
python -m pytest -q                        # 19 tests
python eval/run_eval.py                    # accuracy table -> eval/results.md
```

## Live setup (Gmail + Claude + GitHub + Slack)

### 1. Anthropic
Get an API key from https://console.anthropic.com → `ANTHROPIC_API_KEY`.

### 2. Gmail (do this first — it is the slowest step)
1. https://console.cloud.google.com → create a project → **APIs & Services → Library → Gmail API → Enable**.
2. **OAuth consent screen** → External → fill name/email → **Add test user: your Gmail address**.
3. **Credentials → Create credentials → OAuth client ID → Desktop app** → download JSON →
   save as `credentials.json` in the project root.
4. In Gmail, create a label named `feedback` (Settings → Labels → Create new label).

The first run opens a browser window to authorise; a `token.json` is then cached.

### 3. GitHub
1. Create an empty public repo, e.g. `feedback-triage-demo` → `GITHUB_REPO=you/feedback-triage-demo`.
2. https://github.com/settings/tokens → **Generate new token (classic)** → scope `repo` → `GITHUB_TOKEN`.

### 4. Slack
1. https://api.slack.com/apps → **Create New App → From scratch** → pick your workspace.
2. **Incoming Webhooks → On → Add New Webhook to Workspace** → choose channel → copy URL → `SLACK_WEBHOOK_URL`.

### 5. Configure and verify
```bash
cp .env.example .env      # fill in the values above
python main.py check      # validates .env and pings Gmail, GitHub, Slack
```

### 6. Run
```bash
python main.py seed-inbox        # sends the 10 sample emails to your own Gmail with the label
python main.py run               # one pass; asks y/n before filing critical issues
python main.py run --auto-approve
python main.py run --watch 60    # keep polling every 60s
python eval/run_eval.py --real-llm   # evaluation with the real model
```

## Project layout

```
main.py                      CLI: run | check | seed-inbox
src/agent/
  config.py                  .env -> Settings, live-config validation
  models.py                  FeedbackItem, Classification (validated), TriageResult
  llm.py                     AnthropicClassifier (tool-use schema, retries) + MockClassifier
  dedup.py                   title normalisation + fuzzy duplicate detection
  approval.py                human-in-the-loop gate
  formatting.py              GitHub issue body, duplicate comment, Slack blocks
  pipeline.py                the agent loop with per-item failure isolation
  tracing.py                 JSONL step tracer (inputs/outputs/timing/ok)
  integrations/
    base.py                  InboxClient / IssueTracker / Notifier protocols
    gmail_client.py          Gmail API (OAuth, labels, MIME decoding, send-to-self)
    github_client.py         PyGithub issues + labels
    slack_client.py          incoming webhook
    mock.py                  in-memory twins used by tests / eval / --mock
tests/                       19 pytest tests incl. outage and rejection scenarios
tests/fixtures/sample_feedback.json   10 labelled emails (ground truth for eval)
eval/run_eval.py             accuracy + end-to-end action report -> eval/results.md
RELIABILITY_BRIEF.md         system & reliability brief for judges
```

## Reliability in one paragraph

Every external call is wrapped in retries with exponential back-off and recorded in the trace.
A failure on one email is isolated — it is marked `FAILED`, reported in Slack, and the email is
**left in the inbox** so the next run retries it; nothing is silently dropped. Emails are only
marked processed after the GitHub write succeeds, so a GitHub outage cannot lose feedback. The LLM
output is forced through a JSON schema (tool use) and validated again in code; malformed output
triggers a retry, never a corrupt issue. Critical items require an explicit human `y` before any
write. See `RELIABILITY_BRIEF.md` and `eval/results.md` for the evaluation.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `credentials.json not found` | Download OAuth *Desktop app* JSON from Google Cloud and place it in the project root |
| Google "app not verified / access blocked" | Add your Gmail address as a **test user** on the OAuth consent screen |
| `insufficientPermissions` from Gmail | Delete `token.json` and re-run (scopes changed) |
| Nothing fetched | Emails need the `feedback` label and must not have `triaged`; run `python main.py seed-inbox` |
| GitHub `404 Not Found` | `GITHUB_REPO` must be `owner/repo` and the token needs `repo` scope |
| Slack `no_service` / 404 | Webhook URL was revoked — create a new one |
| `anthropic.AuthenticationError` | Check `ANTHROPIC_API_KEY` |
| `ModuleNotFoundError: src` | Run commands from the project root |

## License

MIT
