"""
DISCOVER AGENT - step 1 of the MedRelay pipeline.

For each source system:
  1. profile it with plain code     (agents/profilers.py - facts, no AI)
  2. mask every sample value        (agents/privacy.py  - no PHI leaves the machine)
  3. ask the LLM to interpret it    -> meaning of each field, PHI flags,
                                       patient identifier, link keys, best
                                       integration pattern, data-quality risks
  4. save outputs/discovery/<system>.json  with status "pending_review"
     (a human approves it in the dashboard before the Map agent uses it)

Usage (from the fhirbridge folder, REST API running on :8001):
  python -m agents.discover                 # all three systems
  python -m agents.discover --only hl7_feed
  python -m agents.discover --no-llm        # profiling only (no API calls)
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import privacy
from agents.profilers import profile_hl7, profile_rest, profile_sqlite

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "discovery"

SYSTEM_PROMPT = """You are a senior healthcare integration engineer.
You analyse source systems so they can be integrated into an HL7 FHIR R4 API.
Sample values are privacy-masked: '#' hides digits and '***' hides letters,
but the format and length are real. Never guess real values.
Be precise, conservative, and reply with JSON only."""

TASK = """Analyse this source-system profile and return JSON with exactly these keys:

{
  "system_summary": "2-3 sentences: what this system is and what clinical data it holds",
  "entities": [
    {"name": "...", "meaning": "...", "likely_fhir_resource": "Patient|Encounter|Condition|Observation|none"}
  ],
  "fields": [
    {
      "name": "exact field name from the profile",
      "meaning": "what the field holds",
      "format": "e.g. YYYYMMDD, DD/MM/YYYY, code list 1/2/9, LOINC code, free text",
      "is_phi": true/false,
      "phi_type": "name|date_of_birth|phone|address|postal_code|identifier|none",
      "role": "patient_identifier|foreign_key|code|value|metadata|lookup|other"
    }
  ],
  "patient_identifier": {"field": "...", "description": "how patients are identified in this system"},
  "link_keys": [{"field": "...", "likely_links_to": "which identifier in other systems this could match, e.g. an MRN"}],
  "integration_pattern": {
    "pattern": "api_wrapper|database_cdc|batch_file_ingest|message_listener",
    "reason": "why this pattern fits"
  },
  "data_quality_notes": ["formats, codes needing lookup, casing, missing values, etc."],
  "risks": ["security / privacy / reliability risks for this integration"]
}

Include EVERY field from the profile in "fields".

PROFILE:
"""


def run_one(name: str, profiler, use_llm: bool) -> dict:
    print(f"\n[{name}] profiling...")
    t0 = time.perf_counter()
    profile = profiler()
    t_profile = time.perf_counter() - t0
    if not profile["fields"]:
        raise RuntimeError(f"no fields found at {profile['location']} - run python scripts/build_all.py first")
    print(f"[{name}] {len(profile['fields'])} fields profiled in {t_profile:.2f}s")

    result = {"system": name, "status": "pending_review",
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "profile": profile, "analysis": None,
              "timing_seconds": {"profile": round(t_profile, 2)}}

    if use_llm:
        from agents.llm import ask_json, model_name
        print(f"[{name}] asking {model_name()} to interpret...")
        t1 = time.perf_counter()
        analysis = ask_json(TASK + json.dumps(profile, indent=1, default=str), system=SYSTEM_PROMPT, label=f"discover:{name}")
        result["timing_seconds"]["llm"] = round(time.perf_counter() - t1, 2)
        result["model"] = model_name()

        # Guardrail: flag any field the model skipped or invented
        profiled = {f["name"] for f in profile["fields"]}
        analysed = {f.get("name") for f in analysis.get("fields", [])}
        result["coverage"] = {
            "profiled_fields": len(profiled),
            "analysed_fields": len(profiled & analysed),
            "missing": sorted(profiled - analysed),
            "invented": sorted(analysed - profiled),
        }
        result["analysis"] = analysis
        print(f"[{name}] done in {result['timing_seconds']['llm']}s | "
              f"coverage {len(profiled & analysed)}/{len(profiled)} | "
              f"PHI fields: {sum(1 for f in analysis.get('fields', []) if f.get('is_phi'))} | "
              f"pattern: {analysis.get('integration_pattern', {}).get('pattern')}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def write_report(results: list[dict]) -> Path:
    lines = ["# MedRelay - Discovery report", "",
             f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | status: **pending human review**", "",
             f"Privacy: sample values masked before any LLM call -> {privacy.summary()}", ""]
    for r in results:
        a = r.get("analysis") or {}
        lines += [f"## {r['system']}  ({r['profile']['kind']})", ""]
        if not a:
            lines += [f"- {len(r['profile']['fields'])} fields profiled (LLM step skipped)", ""]
            continue
        pid = a.get("patient_identifier", {})
        pat = a.get("integration_pattern", {})
        lines += [a.get("system_summary", ""), "",
                  f"- **Patient identifier:** `{pid.get('field')}` - {pid.get('description')}",
                  f"- **Link keys:** " + ", ".join(f"`{k.get('field')}` -> {k.get('likely_links_to')}"
                                                   for k in a.get("link_keys", [])),
                  f"- **Integration pattern:** {pat.get('pattern')} - {pat.get('reason')}",
                  f"- **Coverage:** {r['coverage']['analysed_fields']}/{r['coverage']['profiled_fields']} fields"
                  + (f" (missing: {r['coverage']['missing']})" if r['coverage']['missing'] else ""),
                  f"- **Time:** profile {r['timing_seconds']['profile']}s + LLM {r['timing_seconds'].get('llm')}s",
                  "", "| Field | Meaning | Format | PHI |", "|---|---|---|---|"]
        for f in a.get("fields", []):
            lines.append(f"| `{f.get('name')}` | {f.get('meaning')} | {f.get('format')} | "
                         f"{f.get('phi_type') if f.get('is_phi') else ''} |")
        lines += ["", "**Data quality notes**"] + [f"- {n}" for n in a.get("data_quality_notes", [])]
        lines += ["", "**Risks**"] + [f"- {n}" for n in a.get("risks", [])] + [""]
    path = OUT / "discovery_report.md"
    path.write_text("\n".join(lines))
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["legacy_db", "rest_api", "hl7_feed"])
    ap.add_argument("--no-llm", action="store_true", help="profile only, skip the LLM call")
    ap.add_argument("--api", default="http://localhost:8001", help="REST API base URL")
    args = ap.parse_args()

    systems = {
        "legacy_db": lambda: profile_sqlite(ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db"),
        "rest_api": lambda: profile_rest(args.api),
        "hl7_feed": lambda: profile_hl7(ROOT / "mock_systems" / "hl7_feed" / "outbox"),
    }
    results, failed = [], []
    todo = {n: f for n, f in systems.items() if not args.only or n == args.only}
    with ThreadPoolExecutor(max_workers=3) as pool:   # the 3 systems are independent -> run together
        futures = {name: pool.submit(run_one, name, fn, not args.no_llm) for name, fn in todo.items()}
    for name, fut in futures.items():
        try:
            results.append(fut.result())
        except Exception as e:
            hint = " (is the REST API running? uvicorn mock_systems.rest_api.app:app --port 8001)" \
                if name == "rest_api" else ""
            print(f"[{name}] FAILED: {type(e).__name__}: {e}{hint}")
            failed.append(name)

    report = write_report(results)
    (OUT / "privacy.json").write_text(json.dumps({"masked_values": privacy.summary(),
                                                  "total": sum(privacy.summary().values())}, indent=2))
    print(f"\nPrivacy masking applied: {privacy.summary()}")
    print(f"Report: {report}")
    if failed:
        print(f"Not completed: {failed} - rerun with  --only <system>")
        sys.exit(1)
