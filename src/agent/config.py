"""Central configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # LLM
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-sonnet-4-6"))

    # Gmail
    gmail_credentials_file: str = field(default_factory=lambda: _env("GMAIL_CREDENTIALS_FILE", "credentials.json"))
    gmail_token_file: str = field(default_factory=lambda: _env("GMAIL_TOKEN_FILE", "token.json"))
    gmail_label: str = field(default_factory=lambda: _env("GMAIL_LABEL", "feedback"))
    gmail_max_results: int = field(default_factory=lambda: int(_env("GMAIL_MAX_RESULTS", "20")))

    # GitHub
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN"))
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO"))

    # Slack
    slack_webhook_url: str = field(default_factory=lambda: _env("SLACK_WEBHOOK_URL"))

    # Behaviour
    require_approval_for: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip().lower() for s in _env("REQUIRE_APPROVAL_FOR", "critical").split(",") if s.strip()
        )
    )
    dedup_threshold: int = field(default_factory=lambda: int(_env("DEDUP_THRESHOLD", "80")))
    trace_dir: Path = field(default_factory=lambda: Path(_env("TRACE_DIR", "logs")))

    def validate_for_live(self) -> list[str]:
        """Return a list of missing settings required for a live (non-mock) run."""
        missing: list[str] = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not Path(self.gmail_credentials_file).exists():
            missing.append(f"GMAIL_CREDENTIALS_FILE ({self.gmail_credentials_file} not found)")
        if not self.github_token:
            missing.append("GITHUB_TOKEN")
        if not self.github_repo or "/" not in self.github_repo:
            missing.append("GITHUB_REPO (format owner/repo)")
        if not self.slack_webhook_url.startswith("https://hooks.slack.com/"):
            missing.append("SLACK_WEBHOOK_URL")
        return missing


def get_settings() -> Settings:
    return Settings()
