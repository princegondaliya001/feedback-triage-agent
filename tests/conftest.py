import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.models import FeedbackItem  # noqa: E402
from src.agent.tracing import Tracer  # noqa: E402


@pytest.fixture
def fixture_rows() -> list[dict]:
    return json.loads((ROOT / "tests" / "fixtures" / "sample_feedback.json").read_text(encoding="utf-8"))


@pytest.fixture
def items(fixture_rows) -> list[FeedbackItem]:
    return [FeedbackItem(**{k: v for k, v in r.items() if k != "expected"}) for r in fixture_rows]


@pytest.fixture
def tracer(tmp_path) -> Tracer:
    return Tracer(tmp_path / "logs")
