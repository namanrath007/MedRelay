"""
Where did the time go?  Summarises every LLM call logged in outputs/llm_calls.jsonl.

Usage:  python scripts/llm_timing.py            # all calls
        python scripts/llm_timing.py --last 20  # most recent 20 calls
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "outputs" / "llm_calls.jsonl"


def summary(last: int | None = None) -> list[dict]:
    if not LOG.exists():
        return []
    calls = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    calls = calls[-last:] if last else calls
    by = defaultdict(lambda: {"calls": 0, "from_cache": 0, "failed": 0, "seconds": 0.0, "slowest": 0.0})
    for c in calls:
        b = by[c.get("label") or "other"]
        b["calls"] += 1
        b["from_cache"] += c["cached"]
        b["failed"] += not c["ok"]
        b["seconds"] += c["seconds"]
        b["slowest"] = max(b["slowest"], c["seconds"])
    return [{"step": k, **{x: round(y, 1) if isinstance(y, float) else y for x, y in v.items()}}
            for k, v in sorted(by.items(), key=lambda kv: -kv[1]["seconds"])]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int)
    rows = summary(ap.parse_args().last)
    if not rows:
        raise SystemExit("No LLM calls logged yet.")
    print(f"{'step':24} {'calls':>5} {'cached':>6} {'failed':>6} {'total s':>8} {'slowest s':>9}")
    for r in rows:
        print(f"{r['step']:24} {r['calls']:>5} {r['from_cache']:>6} {r['failed']:>6} {r['seconds']:>8} {r['slowest']:>9}")
    print(f"\nTotal model time: {sum(r['seconds'] for r in rows):.1f}s")
