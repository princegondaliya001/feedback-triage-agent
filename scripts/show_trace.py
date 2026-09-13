"""Pretty-print the latest trace file: python scripts/show_trace.py [path]"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(Path("logs").glob("trace-*.jsonl"), key=lambda p: p.stat().st_mtime)
print(f"# {path}\n")
for line in path.read_text(encoding="utf-8").splitlines():
    e = json.loads(line)
    mark = "ok " if e["ok"] else "ERR"
    ms = e["data"].get("ms", "")
    item = e["item_id"] or "-"
    out = e["data"].get("output") or e["data"].get("error") or {k: v for k, v in e["data"].items() if k not in ("inputs", "ms")}
    print(f"{e['ts'][11:23]}  {mark}  {e['event']:<26} {item:<8} {ms!s:>5}  {json.dumps(out)[:90]}")
