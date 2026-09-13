"""Structured tracing: every tool call and decision is written to a JSONL file.

The trace is the evidence that the agent did what it claims. Each run gets its own
file under TRACE_DIR, and every step records input, output, duration and success.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Tracer:
    def __init__(self, trace_dir: Path, run_id: str | None = None) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.path = trace_dir / f"trace-{self.run_id}.jsonl"
        self._events: list[dict[str, Any]] = []
        self.event("run.start", {})

    # ------------------------------------------------------------------ core
    def event(self, name: str, data: dict[str, Any], *, ok: bool = True, item_id: str | None = None) -> dict[str, Any]:
        record = {
            "ts": _now(),
            "run_id": self.run_id,
            "event": name,
            "ok": ok,
            "item_id": item_id,
            "data": _truncate(data),
        }
        self._events.append(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    @contextmanager
    def step(self, name: str, item_id: str | None = None, **inputs: Any) -> Iterator[dict[str, Any]]:
        """Context manager that records a step with timing and success/failure.

        Usage:
            with tracer.step("github.create_issue", item_id=..., title=...) as out:
                issue = client.create_issue(...)
                out["issue_number"] = issue.number
        """
        started = time.perf_counter()
        output: dict[str, Any] = {}
        try:
            yield output
        except Exception as exc:  # noqa: BLE001 - we want to record *any* failure
            self.event(
                name,
                {"inputs": inputs, "error": f"{type(exc).__name__}: {exc}", "ms": _ms(started)},
                ok=False,
                item_id=item_id,
            )
            raise
        else:
            self.event(name, {"inputs": inputs, "output": output, "ms": _ms(started)}, ok=True, item_id=item_id)

    def finish(self, summary: dict[str, Any]) -> None:
        self.event("run.end", summary)

    # --------------------------------------------------------------- helpers
    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def failures(self) -> list[dict[str, Any]]:
        return [e for e in self._events if not e["ok"]]


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _truncate(data: Any, limit: int = 600) -> Any:
    """Keep trace files readable: clip long strings, recurse into containers."""
    if isinstance(data, str):
        return data if len(data) <= limit else data[:limit] + f"...(+{len(data) - limit} chars)"
    if isinstance(data, dict):
        return {k: _truncate(v, limit) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_truncate(v, limit) for v in data]
    return data
