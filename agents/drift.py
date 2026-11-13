"""
DRIFT MONITOR AGENT - keeps integrations healthy after go-live ("Operate").

  1. DETECT    re-profile the source and compare with the approved baseline
               (fields removed / added) and run the live adapter -> does it still work?
  2. DIAGNOSE  pair each removed field with its most likely replacement
               (same table, same type, same value format, same cardinality),
               and ask the LLM to confirm and explain (optional; falls back to rules)
  3. REPAIR    patch the mapping + adapter code, re-run ALL validation checks
  4. PROPOSE   save a diff + results as a proposal: a human approves before go-live

Usage:
  python -m agents.drift                # detect + propose a fix (legacy_db)
  python -m agents.drift --approve      # apply the approved proposal and republish
  python -m agents.drift --no-llm       # rule-based diagnosis only
"""
import argparse
import difflib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agents.profilers import profile_sqlite
from agents.validate import ADAPTERS, publish, run_checks, summarize

ROOT = Path(__file__).resolve().parents[1]
DISC = ROOT / "outputs" / "discovery" / "legacy_db.json"
MAPPING = ROOT / "outputs" / "mapping" / "legacy_db.json"
OUT = ROOT / "outputs" / "drift"
DB = ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db"
SYSTEM = "legacy_db"


def _shape(field: dict) -> tuple:
    return tuple(sorted(set(field.get("samples") or field.get("all_values") or [])))[:3]


def pair_fields(removed: list[dict], added: list[dict]) -> list[dict]:
    pairs = []
    for r in removed:
        table = r["name"].split(".")[0]
        best, best_score = None, 0.0
        for a in added:
            if a["name"].split(".")[0] != table:
                continue
            score = 0.0
            score += 0.35 if a.get("type") == r.get("type") else 0
            score += 0.35 if _shape(a) == _shape(r) else 0
            dr, da = r.get("distinct", 0) or 0, a.get("distinct", 0) or 0
            score += 0.30 * (min(dr, da) / max(dr, da)) if max(dr, da) else 0.30
            if score > best_score:
                best, best_score = a, score
        if best and best_score >= 0.6:
            pairs.append({"old": r["name"], "new": best["name"], "rule_score": round(best_score, 2)})
    return pairs


def llm_confirm(pairs: list[dict], removed: list[dict], added: list[dict]) -> list[dict]:
    from agents.llm import ask_json
    prompt = (
        "A legacy healthcare database schema changed. Fields were removed and added (sample values "
        "are privacy-masked; formats are real). For each proposed rename, confirm whether the new field "
        "is the same data as the old one.\n\n"
        f"Removed: {json.dumps(removed, indent=1)}\nAdded: {json.dumps(added, indent=1)}\n"
        f"Proposed renames: {json.dumps(pairs)}\n\n"
        'Return {"pairs": [{"old": "...", "new": "...", "confirmed": true, "confidence": 0.0, '
        '"reason": "one sentence"}]}')
    result = {p.get("old"): p for p in ask_json(prompt, label="drift").get("pairs", [])}
    for p in pairs:
        r = result.get(p["old"], {})
        p.update({"llm_confirmed": bool(r.get("confirmed")), "llm_confidence": r.get("confidence"),
                  "reason": r.get("reason", "")})
    return pairs


def detect_and_propose(use_llm: bool = True) -> dict:
    t0 = time.perf_counter()
    baseline = json.loads(DISC.read_text())
    base_fields = {f["name"]: f for f in baseline["profile"]["fields"]}
    current = profile_sqlite(DB)
    cur_fields = {f["name"]: f for f in current["fields"]}
    removed = [base_fields[n] for n in base_fields if n not in cur_fields]
    added = [cur_fields[n] for n in cur_fields if n not in base_fields]

    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    code = (ADAPTERS / f"{SYSTEM}.py").read_text()
    live, _ = run_checks(SYSTEM, code, truth)
    report = {"system": SYSTEM, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "removed": [f["name"] for f in removed], "added": [f["name"] for f in added],
              "live_adapter": summarize(live), "live_errors": live["runtime_examples"][:2]}
    print(f"[drift] removed {report['removed'] or 'none'} | added {report['added'] or 'none'}")
    print(f"[drift] live adapter: {report['live_adapter']}")

    if not removed and not added:
        report["status"] = "healthy"
    else:
        pairs = pair_fields(removed, added)
        if use_llm and pairs:
            try:
                pairs = llm_confirm(pairs, removed, added)
            except Exception as e:
                print(f"[drift] LLM confirmation unavailable ({e}); using rule-based diagnosis")
        report["diagnosis"] = pairs
        for p in pairs:
            print(f"[drift] {p['old']} -> {p['new']}  (rule score {p['rule_score']}"
                  + (f", LLM confirmed={p.get('llm_confirmed')}: {p.get('reason')}" if "llm_confirmed" in p else "") + ")")

        new_code = code
        for p in pairs:
            new_code = new_code.replace(f'"{p["old"]}"', f'"{p["new"]}"').replace(f"'{p['old']}'", f"'{p['new']}'")
        fixed, _ = run_checks(SYSTEM, new_code, truth)
        print(f"[drift] patched adapter: {summarize(fixed)}")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{SYSTEM}.proposed.py").write_text(new_code)
        report.update({
            "proposed_fix": summarize(fixed), "fix_passed": fixed["passed"],
            "diff": "".join(difflib.unified_diff(code.splitlines(True), new_code.splitlines(True),
                                                 "adapter (live)", "adapter (proposed)")),
            "status": "fix_pending_approval" if fixed["passed"] else "needs_human",
        })
    report["seconds_to_diagnose_and_fix"] = round(time.perf_counter() - t0, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(report, indent=2))
    print(f"[drift] status: {report['status']}  ({report['seconds_to_diagnose_and_fix']}s)")
    return report


def approve() -> dict:
    report = json.loads((OUT / "latest.json").read_text())
    if report.get("status") != "fix_pending_approval":
        raise SystemExit(f"Nothing to approve (status: {report.get('status')})")
    new_code = (OUT / f"{SYSTEM}.proposed.py").read_text()
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    res, produced = run_checks(SYSTEM, new_code, truth)
    if not res["passed"]:
        raise SystemExit("Proposed fix no longer passes validation - not applied")
    backup = OUT / "backup"   # lets  scripts/simulate_drift.py --reset  restore the demo
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "legacy_db.py").write_bytes((ADAPTERS / f"{SYSTEM}.py").read_bytes())
    (backup / "mapping_legacy_db.json").write_bytes(MAPPING.read_bytes())
    (backup / "discovery_legacy_db.json").write_bytes(DISC.read_bytes())
    publish(SYSTEM, new_code, produced)

    renames = {p["old"]: p["new"] for p in report["diagnosis"]}
    mapping = json.loads(MAPPING.read_text())
    for m in mapping["mappings"]:
        m["source"] = renames.get(m["source"], m["source"])
    MAPPING.write_text(json.dumps(mapping, indent=2))
    disc = json.loads(DISC.read_text())
    disc["profile"] = profile_sqlite(DB)
    for f in (disc.get("analysis") or {}).get("fields", []):
        f["name"] = renames.get(f["name"], f["name"])
    DISC.write_text(json.dumps(disc, indent=2, default=str))

    report["status"] = "fixed"
    report["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2))
    print(f"[drift] fix approved and published: {renames}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    approve() if a.approve else detect_and_propose(use_llm=not a.no_llm)
