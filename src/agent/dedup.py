"""Duplicate detection against existing open issues using fuzzy title matching."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .integrations.base import ExistingIssue

_STOPWORDS = {"the", "a", "an", "is", "are", "on", "in", "when", "to", "of", "and", "for", "with", "not", "my", "i", "it"}


_SYNONYMS = {"login": "log", "logging": "log", "signin": "log", "resetting": "reset", "resets": "reset",
             "cannot": "cant", "can't": "cant", "unable": "cant", "broken": "fail", "fails": "fail", "failing": "fail",
             "failure": "fail", "crashes": "crash", "crashing": "crash", "errors": "error"}


def _stem(word: str) -> str:
    word = _SYNONYMS.get(word, word)
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def normalize(title: str) -> str:
    """Lower-case, strip reply prefixes/punctuation/stopwords, and lightly stem so
    'Login broken after resetting password' ~ 'Cannot log in after password reset'."""
    title = re.sub(r"^(re|fwd?|fw):\s*", "", title, flags=re.I)
    title = re.sub(r"[^a-z0-9' ]+", " ", title.lower())
    words = [_stem(w) for w in title.split() if w not in _STOPWORDS]
    return " ".join(words)


def find_duplicate(title: str, existing: list[ExistingIssue], threshold: int) -> tuple[ExistingIssue | None, int]:
    """Return (best matching issue, score) if score >= threshold, else (None, best score)."""
    target = normalize(title)
    if not target:
        return None, 0
    best: ExistingIssue | None = None
    best_score = 0
    for issue in existing:
        score = int(fuzz.token_set_ratio(target, normalize(issue.title)))
        if score > best_score:
            best, best_score = issue, score
    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score
