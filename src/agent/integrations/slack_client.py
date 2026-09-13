"""Slack integration via an incoming webhook (no bot token needed)."""

from __future__ import annotations

import requests
from tenacity import retry, stop_after_attempt, wait_exponential


class SlackWebhook:
    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        if not webhook_url.startswith("https://hooks.slack.com/"):
            raise ValueError("SLACK_WEBHOOK_URL must be a Slack incoming webhook URL")
        self._url = webhook_url
        self._timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def post(self, text: str, blocks: list[dict] | None = None) -> None:
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        resp = requests.post(self._url, json=payload, timeout=self._timeout)
        if resp.status_code >= 400:
            raise ConnectionError(f"Slack webhook returned {resp.status_code}: {resp.text[:200]}")
