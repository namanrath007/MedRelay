"""
VALIDATE AGENT - step 4 of the MedRelay pipeline, with a SELF-HEALING loop.

  generate -> security scan -> run on EVERY source record -> FHIR structure check
           -> fidelity vs truth data -> PASS?  publish
                                     -> FAIL?  errors (PHI-masked) go back to the
                                               Generate agent -> retry (max 3)

Usage:
  python -m agents.validate                      # generate + validate all systems
  python -m agents.validate --only legacy_db
  python -m agents.validate --check-only         # re-validate existing adapters, no LLM
  python -m agents.validate --adapter-dir tests/reference_adapters --check-only   (self-test)

Outputs:
  generated/adapters/<system>.py           the approved adapter
  outputs/validation/<system>.json         every attempt, every check, timings
  outputs/fhir_store/<system>.json         FHIR resources produced (published)
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time
import traceback
import types
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agents.checks import fhir_structure, fidelity, security_scan
from agents.privacy import mask_value
from fhirbridge_runtime.connectors import iter_source

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "generated" / "adapters"
VALID = ROOT / "outputs" / "validation"
STORE = ROOT / "outputs" / "fhir_store"
MAX_ATTEMPTS = 3
FIDELITY_TARGET = 99.0


def load_module(code: str, name: str):
    mod = types.ModuleType(f"adapter_{name}")
    exec(compile(code, f"<adapter {name}>", "exec"), mod.__dict__)  # only after security_scan passed
    return mod


def run_checks(system: str, code: str, truth: dict) -> dict:
    """Run all checks; return a result dict (never raises)."""
    t0 = time.perf_counter()
    res = {"security": [], "runtime_errors": 0, "runtime_examples": [], "records": 0,
           "resources": Counter(), "structure_errors": 0, "structure_examples": Counter(),
           "fidelity": None, "passed": False}
    res["security"] = security_scan(code)
    if res["security"]:
        res["seconds"] = round(time.perf_counter() - t0, 2)
        return res, []
    try:
        mod = load_module(code, system)
        to_fhir = mod.to_fhir
    except Exception as e:
        res["runtime_errors"] = 1
        res["runtime_examples"].append(f"module failed to load: {type(e).__name__}: {e}")
        res["seconds"] = round(time.perf_counter() - t0, 2)
        return res, []

    produced = []
    for entity, record in iter_source(system):
        res["records"] += 1
        try:
            out = to_fhir(entity, dict(record))
            if not isinstance(out, list):
                raise TypeError(f"to_fhir must return a list, got {type(out).__name__}")
        except Exception as e:
            res["runtime_errors"] += 1
            if len(res["runtime_examples"]) < 5:
                tb = traceback.extract_tb(e.__traceback__)[-1]
                masked = {k: mask_value(k, v) for k, v in record.items()}
                res["runtime_examples"].append(
                    f"entity={entity}: {type(e).__name__}: {e} (line {tb.lineno}); record={json.dumps(masked)}")
            continue
        for r in out:
            res["resources"][r.get("resourceType", "?") if isinstance(r, dict) else "?"] += 1
            for err in fhir_structure(r):
                res["structure_errors"] += 1
                res["structure_examples"][err] += 1
            produced.append(r)

    try:
        res["fidelity"] = fidelity(system, produced, truth)
    except Exception as e:  # never let a malformed resource crash the checker
        res["fidelity"] = {"checks": 1, "passed": 0, "fidelity_pct": 0.0,
                           "failures": [{"check": f"fidelity check crashed: {type(e).__name__}: {e}",
                                         "resource": "?", "expected": "well-formed FHIR", "got": "?"}]}
    res["passed"] = (not res["security"] and res["runtime_errors"] == 0 and res["structure_errors"] == 0
                     and res["records"] > 0 and res["fidelity"]["fidelity_pct"] >= FIDELITY_TARGET)
    res["resources"] = dict(res["resources"])
    res["structure_examples"] = dict(res["structure_examples"].most_common(10))
    res["seconds"] = round(time.perf_counter() - t0, 2)
    return res, produced


def feedback_text(res: dict) -> str:
    """Turn check results into instructions for the next attempt (values are masked)."""
    lines = []
    if res["security"]:
        lines += ["SECURITY (must fix):"] + [f"- {s}" for s in res["security"]]
    if res["runtime_errors"]:
        lines += [f"RUNTIME: {res['runtime_errors']} records raised errors. Examples:"] + \
                 [f"- {e}" for e in res["runtime_examples"]]
    if res["structure_errors"]:
        lines += [f"FHIR STRUCTURE: {res['structure_errors']} problems. Most common:"] + \
                 [f"- {msg}  (x{n})" for msg, n in res["structure_examples"].items()]
    fid = res.get("fidelity")
    if fid and fid["failures"]:
        counts = Counter(f["check"] for f in fid["failures"])
        lines += [f"DATA FIDELITY {fid['fidelity_pct']}% (target {FIDELITY_TARGET}%). Failing checks:"]
        for check, n in counts.most_common(8):
            ex = next(f for f in fid["failures"] if f["check"] == check)
            lines.append(f"- {check} wrong in {n} cases; e.g. expected format "
                         f"{mask_value(check, ex['expected'])!r}, got {mask_value(check, ex['got'])!r}")
    return "\n".join(lines) or "All checks passed."


def summarize(res: dict) -> str:
    fid = res.get("fidelity") or {}
    return (f"security {'OK' if not res['security'] else str(len(res['security'])) + ' issue(s)'} | "
            f"records {res['records']} | runtime errors {res['runtime_errors']} | "
            f"FHIR errors {res['structure_errors']} | fidelity {fid.get('fidelity_pct', '-')}% | "
            f"{'PASS' if res['passed'] else 'FAIL'}")


def publish(system: str, code: str, resources: list[dict]):
    ADAPTERS.mkdir(parents=True, exist_ok=True)
    STORE.mkdir(parents=True, exist_ok=True)
    (ADAPTERS / f"{system}.py").write_text(code)
    for r in resources:
        r.setdefault("meta", {})["source"] = f"fhirbridge:{system}"
    (STORE / f"{system}.json").write_text(json.dumps(resources))


def heal_loop(system: str, truth: dict, use_llm: bool = True, adapter_dir: Path = ADAPTERS) -> dict:
    attempts, code, res, produced = [], None, None, []
    t_start = time.perf_counter()
    if not use_llm:
        code = (adapter_dir / f"{system}.py").read_text()
        res, produced = run_checks(system, code, truth)
        attempts.append({"attempt": 1, "source": f"existing adapter ({adapter_dir.name})",
                         "summary": summarize(res), "result": res, "code": code})
        print(f"[{system}] check: {summarize(res)}")
    else:
        from agents.generate import generate_code
        feedback = None
        for n in range(1, MAX_ATTEMPTS + 1):
            print(f"[{system}] attempt {n}: generating adapter...")
            t0 = time.perf_counter()
            gen = generate_code(system, previous_code=code, feedback=feedback)
            t_gen = round(time.perf_counter() - t0, 2)
            code = gen["code"]
            res, produced = run_checks(system, code, truth)
            print(f"[{system}] attempt {n}: {summarize(res)}  (generated in {t_gen}s)")
            attempts.append({"attempt": n, "source": gen["model"], "notes": gen["notes"],
                             "generate_seconds": t_gen, "summary": summarize(res),
                             "result": res, "feedback_sent": feedback, "code": code})
            if res["passed"]:
                break
            if callable(gen.get("forget")):
                gen["forget"]()   # never replay failing code from the cache on a later run
            feedback = feedback_text(res)

    passed = bool(res and res["passed"])
    if passed:
        publish(system, code, produced)
    report = {"system": system, "passed": passed, "attempts_used": len(attempts),
              "status": "ready_for_approval" if passed else "needs_human_fix",
              "total_seconds": round(time.perf_counter() - t_start, 2),
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "fidelity_target_pct": FIDELITY_TARGET, "attempts": attempts}
    VALID.mkdir(parents=True, exist_ok=True)
    (VALID / f"{system}.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"[{system}] {'PASSED' if passed else 'FAILED'} after {len(attempts)} attempt(s) -> "
          f"{'published' if passed else 'needs a human'}\n")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["legacy_db", "rest_api", "hl7_feed"])
    ap.add_argument("--check-only", action="store_true", help="validate existing adapters, no LLM")
    ap.add_argument("--adapter-dir", default=str(ADAPTERS))
    args = ap.parse_args()
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    failed, todo = [], []
    for system in ("legacy_db", "rest_api", "hl7_feed"):
        if args.only and system != args.only:
            continue
        if not args.check_only and not (ROOT / "outputs" / "mapping" / f"{system}.json").exists():
            print(f"[{system}] SKIPPED: no mapping yet - run  python -m agents.map --only {system}  first")
            failed.append(system)
            continue
        todo.append(system)
    with ThreadPoolExecutor(max_workers=3) as pool:   # the 3 systems are independent -> run together
        futures = {s: pool.submit(heal_loop, s, truth, not args.check_only, Path(args.adapter_dir)) for s in todo}
    for system, fut in futures.items():
        try:
            if not fut.result()["passed"]:
                failed.append(system)
        except Exception as e:
            hint = " (is the REST API running on :8001?)" if system == "rest_api" else ""
            print(f"[{system}] FAILED: {type(e).__name__}: {e}{hint}")
            failed.append(system)
    if failed:
        print(f"Not completed: {failed}")
        sys.exit(1)
