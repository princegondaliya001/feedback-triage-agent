from src.agent.dedup import find_duplicate, normalize
from src.agent.integrations.base import ExistingIssue


def test_normalize_strips_prefixes_and_stopwords():
    assert normalize("Re: The login is broken") == "log fail"
    assert set(normalize("Cannot log in after password reset").split()) == set(normalize("can't log in after resetting password").split())


def test_detects_near_duplicate():
    existing = [ExistingIssue(1, "Cannot log in after password reset", "u1"), ExistingIssue(2, "Dark mode", "u2")]
    match, score = find_duplicate("Login broken after resetting password", existing, threshold=60)
    assert match is not None and match.number == 1
    assert score >= 60


def test_no_false_positive_on_unrelated_titles():
    existing = [ExistingIssue(1, "Cannot log in after password reset", "u1")]
    match, score = find_duplicate("Export to CSV fails with 500 error", existing, threshold=80)
    assert match is None
    assert score < 80


def test_empty_existing_list():
    assert find_duplicate("anything", [], 80) == (None, 0)
