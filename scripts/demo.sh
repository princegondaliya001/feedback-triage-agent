#!/usr/bin/env bash
# Two-minute demo script. Run each block on camera.
set -e
cd "$(dirname "$0")/.."

echo "=== 1. Tests ==="; python -m pytest -q
echo; echo "=== 2. Evaluation ==="; python eval/run_eval.py | tail -10
echo; echo "=== 3. Seed inbox with sample feedback ==="; python main.py seed-inbox --limit 5
echo "waiting 10s for Gmail to deliver..."; sleep 10
echo; echo "=== 4. Live run: Gmail -> Claude -> GitHub -> Slack ==="; python main.py run
echo; echo "Now open GitHub Issues and the Slack channel on screen."
