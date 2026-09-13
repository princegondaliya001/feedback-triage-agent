"""Gmail integration via the official Google API client.

Feedback emails are selected by a Gmail label (default: "feedback"). After an email
is processed the agent adds a "triaged" label and removes UNREAD, so a re-run never
double-processes the same message.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import FeedbackItem

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PROCESSED_LABEL = "triaged"


def _load_credentials(credentials_file: str, token_file: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not Path(credentials_file).exists():
            raise FileNotFoundError(
                f"{credentials_file} not found. Download OAuth 'Desktop app' credentials from Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
        creds = flow.run_local_server(port=0)
    Path(token_file).write_text(creds.to_json(), encoding="utf-8")
    return creds


def _decode_body(payload: dict) -> str:
    """Walk the MIME tree and return the first text/plain part (fallback: text/html stripped)."""
    stack = [payload]
    html_fallback = ""
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            text = base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
            if mime == "text/plain":
                return text
            if mime == "text/html" and not html_fallback:
                html_fallback = re.sub(r"<[^>]+>", " ", text)
        stack.extend(part.get("parts", []))
    return re.sub(r"\s+", " ", html_fallback).strip()


class GmailInbox:
    def __init__(self, credentials_file: str, token_file: str, label: str) -> None:
        from googleapiclient.discovery import build

        creds = _load_credentials(credentials_file, token_file)
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._label = label
        self._processed_label_id = self._ensure_label(PROCESSED_LABEL)

    # ------------------------------------------------------------ labels
    def _ensure_label(self, name: str) -> str:
        labels = self._svc.users().labels().list(userId="me").execute().get("labels", [])
        for lab in labels:
            if lab["name"].lower() == name.lower():
                return lab["id"]
        created = self._svc.users().labels().create(
            userId="me", body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        ).execute()
        return created["id"]

    # ------------------------------------------------------------ reading
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def fetch_unprocessed(self, limit: int) -> list[FeedbackItem]:
        query = f"label:{self._label} -label:{PROCESSED_LABEL}"
        resp = self._svc.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        items: list[FeedbackItem] = []
        for ref in resp.get("messages", []):
            msg = self._svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            items.append(
                FeedbackItem(
                    id=msg["id"],
                    sender=headers.get("from", "unknown"),
                    subject=headers.get("subject", "(no subject)"),
                    body=_decode_body(msg["payload"]) or msg.get("snippet", ""),
                    received_at=headers.get("date", ""),
                )
            )
        return items

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def mark_processed(self, item_id: str) -> None:
        self._svc.users().messages().modify(
            userId="me",
            id=item_id,
            body={"addLabelIds": [self._processed_label_id], "removeLabelIds": ["UNREAD"]},
        ).execute()

    # ------------------------------------------------------------ sending (demo helper)
    def send_to_self(self, subject: str, body: str) -> str:
        """Send an email to the authenticated account and apply the feedback label."""
        from email.mime.text import MIMEText

        profile = self._svc.users().getProfile(userId="me").execute()
        me = profile["emailAddress"]
        mime = MIMEText(body)
        mime["to"] = me
        mime["from"] = me
        mime["subject"] = subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = self._svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        feedback_label_id = self._ensure_label(self._label)
        self._svc.users().messages().modify(
            userId="me", id=sent["id"], body={"addLabelIds": [feedback_label_id]}
        ).execute()
        return sent["id"]
