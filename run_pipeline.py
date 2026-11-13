"""
Run the whole MedRelay pipeline with one command and collect the metrics.

  python run_pipeline.py                 # discover -> map -> evaluate -> generate+validate
  python run_pipeline.py --from map      # start from a later step
  python run_pipeline.py --only rest_api

Needs the mock portal API running:  python -m uvicorn mock_systems.rest_api.app:app --port 8001
Writes outputs/pipeline_summary.json (used by the dashboard and your slides).
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = ["discover", "map", "evaluate", "validate"]
CMDS = {"discover": [sys.executable, "-m", "agents.discover"],
        "map": [sys.executable, "-m", "agents.map"],
        "evaluate": [sys.executable, "scripts/evaluate_mapping.py"],
        "validate": [sys.executable, "-m", "agents.validate"]}


def api_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8001/health", timeout=2)
        return True
    except Exception:
        return False


def load(path):
    p = ROOT / path
    return json.loads(p.read_text()) if p.exists() else None


def collect_summary(step_seconds: dict) -> dict:
    summary = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "wall_clock_seconds_per_step": step_seconds, "systems": {}}
    ev = load("outputs/mapping/evaluation.json")
    if ev:
        summary["mapping_evaluation"] = ev["summary"]
    for s in ("legacy_db", "rest_api", "hl7_feed"):
        d, m, v = (load(f"outputs/discovery/{s}.json"), load(f"outputs/mapping/{s}.json"),
                   load(f"outputs/validation/{s}.json"))
        info = {}
        if d:
            info["discover_seconds"] = sum(x for x in d["timing_seconds"].values() if x)
            info["fields"] = len(d["profile"]["fields"])
        if m:
            info["map_seconds"] = sum(x for x in m["timing_seconds"].values() if x)
            info["auto_approved"] = sum(x["status"] == "auto_approved" for x in m["mappings"])
            info["needs_review"] = sum(x["status"] == "needs_review" for x in m["mappings"])
        if v:
            last = v["attempts"][-1]["result"]
            info.update({"validated": v["passed"], "attempts": v["attempts_used"],
                         "build_and_validate_seconds": v["total_seconds"],
                         "fidelity_pct": (last.get("fidelity") or {}).get("fidelity_pct"),
                         "records_processed": last.get("records"), "resources": last.get("resources")})
        info["total_agent_seconds"] = round(sum(info.get(k, 0) or 0 for k in
                                                ("discover_seconds", "map_seconds", "build_and_validate_seconds")), 1)
        summary["systems"][s] = info
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / "pipeline_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", choices=STEPS, default="discover")
    ap.add_argument("--only", choices=["legacy_db", "rest_api", "hl7_feed"])
    a = ap.parse_args()

    if not api_up():
        print("WARNING: portal API not reachable on :8001 - start it first:\n"
              "  python -m uvicorn mock_systems.rest_api.app:app --port 8001\n")
    seconds = {}
    for step in STEPS[STEPS.index(a.start):]:
        cmd = CMDS[step] + (["--only", a.only] if a.only and step != "evaluate" else [])
        print(f"\n{'=' * 20} {step.upper()} {'=' * 20}")
        t0 = time.perf_counter()
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        seconds[step] = round(time.perf_counter() - t0, 1)
        if rc != 0:
            print(f"WARNING: step '{step}' did not complete for every system - continuing with the rest.")
            seconds[step] = f"{seconds[step]} (incomplete)"
    s = collect_summary(seconds)
    print(f"\n{'=' * 20} SUMMARY {'=' * 20}")
    for name, info in s["systems"].items():
        print(f"{name:10} fields {info.get('fields', '-'):>3} | validated {info.get('validated', '-')} "
              f"in {info.get('attempts', '-')} attempt(s) | fidelity {info.get('fidelity_pct', '-')}% | "
              f"agent time {info.get('total_agent_seconds', '-')}s")
    if "mapping_evaluation" in s:
        e = s["mapping_evaluation"]
        print(f"mapping accuracy {e['fhirbridge_accuracy_pct']}% (ML baseline {e['ml_baseline_accuracy_pct']}%)")
    print("Saved outputs/pipeline_summary.json")
