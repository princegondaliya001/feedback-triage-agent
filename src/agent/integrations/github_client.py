"""GitHub Issues integration via PyGithub."""

from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential

from .base import ExistingIssue


class GitHubIssues:
    def __init__(self, token: str, repo_full_name: str) -> None:
        from github import Auth, Github

        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        if "/" not in repo_full_name:
            raise ValueError("GITHUB_REPO must look like owner/repo")
        self._gh = Github(auth=Auth.Token(token))
        self._repo = self._gh.get_repo(repo_full_name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def list_open_issues(self, limit: int = 200) -> list[ExistingIssue]:
        out: list[ExistingIssue] = []
        for issue in self._repo.get_issues(state="open"):
            if issue.pull_request is not None:
                continue
            out.append(ExistingIssue(number=issue.number, title=issue.title, url=issue.html_url, state=issue.state))
            if len(out) >= limit:
                break
        return out

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def create_issue(self, title: str, body: str, labels: list[str]) -> ExistingIssue:
        self._ensure_labels(labels)
        issue = self._repo.create_issue(title=title, body=body, labels=labels)
        return ExistingIssue(number=issue.number, title=issue.title, url=issue.html_url, state=issue.state)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
    def add_comment(self, issue_number: int, body: str) -> None:
        self._repo.get_issue(number=issue_number).create_comment(body)

    def _ensure_labels(self, labels: list[str]) -> None:
        from github import GithubException

        existing = {lab.name for lab in self._repo.get_labels()}
        palette = {"bug": "d73a4a", "feature": "a2eeef", "question": "d876e3", "critical": "b60205", "high": "e99695", "medium": "fbca04", "low": "c2e0c6"}
        for name in labels:
            if name in existing:
                continue
            try:
                self._repo.create_label(name=name, color=palette.get(name, "ededed"))
            except GithubException:
                pass  # label was created concurrently or we lack permission; create_issue will still work
