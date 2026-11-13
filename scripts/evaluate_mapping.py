"""
Score the Map agent against ground_truth/mappings.json.

Reports, per system and overall:
  * ML baseline accuracy     (TF-IDF top-1 only)
  * MedRelay accuracy      (hybrid ML + LLM final answer)
  * auto-approved: how many, and how accurate   <- trust in automation
  * needs-review: how many                      <- human effort remaining
  * "none" handling: did it correctly refuse to map lookup/surrogate fields?

Usage:  python scripts/evaluate_mapping.py
Output: outputs/mapping/evaluation.json + evaluation.md
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "outputs" / "mapping"
truth = json.loads((ROOT / "ground_truth" / "mappings.json").read_text())


def ok(pred, expected) -> bool:
    accepted = expected if isinstance(expected, list) else [expected]
    return pred in accepted


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


rows, per_system = [], {}
for system in ("legacy_db", "rest_api", "hl7_feed"):
    fp = MAP / f"{system}.json"
    if not fp.exists():
        continue
    preds = {m["source"]: m for m in json.loads(fp.read_text())["mappings"]}
    s = {"scored": 0, "ml_correct": 0, "final_correct": 0, "auto": 0, "auto_correct": 0,
         "review": 0, "none_expected": 0, "none_correct": 0, "errors": []}
    for gt in truth[system]:
        m = preds.get(gt["source"])
        s["scored"] += 1
        if m is None:
            s["errors"].append({"source": gt["source"], "expected": gt["target"], "got": "MISSING"})
            continue
        final_ok, ml_ok = ok(m["target"], gt["target"]), ok(m["ml_top1"], gt["target"])
        s["ml_correct"] += ml_ok
        s["final_correct"] += final_ok
        if m["status"] == "auto_approved":
            s["auto"] += 1
            s["auto_correct"] += final_ok
        else:
            s["review"] += 1
        if gt["target"] is None:
            s["none_expected"] += 1
            s["none_correct"] += final_ok
        if not final_ok:
            s["errors"].append({"source": gt["source"], "expected": gt["target"], "got": m["target"],
                                "confidence": m["confidence"], "status": m["status"]})
        rows.append((system, gt["source"], final_ok))
    per_system[system] = s

tot = {k: sum(s[k] for s in per_system.values())
       for k in ("scored", "ml_correct", "final_correct", "auto", "auto_correct", "review",
                 "none_expected", "none_correct")}
summary = {
    "fields_scored": tot["scored"],
    "ml_baseline_accuracy_pct": pct(tot["ml_correct"], tot["scored"]),
    "fhirbridge_accuracy_pct": pct(tot["final_correct"], tot["scored"]),
    "auto_approved_pct_of_fields": pct(tot["auto"], tot["scored"]),
    "auto_approved_precision_pct": pct(tot["auto_correct"], tot["auto"]),
    "sent_to_human_review": tot["review"],
    "correctly_left_unmapped": f"{tot['none_correct']}/{tot['none_expected']}",
}

lines = ["# MedRelay - Mapping evaluation", "",
         "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items()] + [
    "", "| System | Scored | ML baseline | MedRelay | Auto-approved (precision) | Needs review |",
    "|---|---|---|---|---|---|"]
for name, s in per_system.items():
    lines.append(f"| {name} | {s['scored']} | {pct(s['ml_correct'], s['scored'])}% | "
                 f"{pct(s['final_correct'], s['scored'])}% | {s['auto']} ({pct(s['auto_correct'], s['auto'])}%) | {s['review']} |")
lines += ["", "## Errors"]
for name, s in per_system.items():
    for e in s["errors"]:
        lines.append(f"- {name} `{e['source']}`: expected `{e['expected']}`, got `{e['got']}`"
                     + (f" (conf {e.get('confidence')}, {e.get('status')})" if "confidence" in e else ""))

MAP.mkdir(parents=True, exist_ok=True)
(MAP / "evaluation.json").write_text(json.dumps({"summary": summary, "per_system": per_system}, indent=2))
(MAP / "evaluation.md").write_text("\n".join(lines))

print("\n".join(lines[:len(summary) + 4]))
print()
print("\n".join(lines[len(summary) + 5:len(summary) + 7 + len(per_system)]))
n_err = sum(len(s["errors"]) for s in per_system.values())
print(f"\n{n_err} errors listed in outputs/mapping/evaluation.md")
