"""
MAP AGENT - step 2 of the MedRelay pipeline.

For every source field, predict the FHIR R4 target + transform + confidence.

Two stages (hybrid ML + LLM):
  Stage 1  ML retrieval   TF-IDF similarity between an enriched description of the
                          source field (name with abbreviations expanded + meaning and
                          format from the Discover agent) and every target in
                          agents/fhir_catalog.py  ->  top-5 ranked candidates.
                          Cheap, deterministic, explainable - this is our baseline.
  Stage 2  LLM re-rank    Gemini sees the field, its masked samples and the top-5
                          candidates, picks the final target, the transform and a
                          confidence score.

Confidence gate:  final >= 0.80 -> auto_approved,  else -> needs_review (human).

Usage:
  python -m agents.map                 # all systems discovered so far
  python -m agents.map --no-llm        # ML retrieval only (baseline)
  python scripts/evaluate_mapping.py   # score against the answer key
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import math
import re
import time
from collections import Counter
from pathlib import Path

from agents.fhir_catalog import ABBREVIATIONS, CATALOG

ROOT = Path(__file__).resolve().parents[1]
DISC = ROOT / "outputs" / "discovery"
OUT = ROOT / "outputs" / "mapping"
THRESHOLD = 0.80
TOP_K = 5
STOP = {"the", "a", "of", "in", "to", "and", "or", "for", "is", "this", "field", "value", "e", "g"}


# ------------------------------------------------------------- Stage 1: TF-IDF retrieval
def tokenize(text: str) -> list[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)          # camelCase -> camel Case
    words = re.split(r"[^a-zA-Z0-9]+", text.lower())
    out = []
    for w in words:
        if not w or w in STOP or w.isdigit():
            continue
        for t in ABBREVIATIONS.get(w, w).split():
            out.append(t[:-1] if len(t) > 4 and t.endswith("s") else t)  # tiny stemmer
    return out


class Retriever:
    def __init__(self, catalog: dict):
        self.targets = list(catalog)
        docs = [tokenize(t.replace(".", " ") + " " + d) for t, d in catalog.items()]
        df = Counter(tok for d in docs for tok in set(d))
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = [self._vec(d) for d in docs]

    def _vec(self, toks):
        tf = Counter(toks)
        v = {t: c * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def rank(self, text: str, k: int = TOP_K):
        q = self._vec(tokenize(text))
        scores = [(t, sum(q.get(tok, 0) * w for tok, w in v.items())) for t, v in zip(self.targets, self.vecs)]
        return [(t, round(s, 3)) for t, s in sorted(scores, key=lambda x: -x[1])[:k]]


# ------------------------------------------------------------- build the field list
def load_fields(discovery: dict) -> list[dict]:
    """Merge profile facts with the Discover agent's interpretation.
    HL7 fields with ^-components are split (PID-5 -> PID-5.1 family, PID-5.2 given...)."""
    meaning = {f.get("name"): f for f in (discovery.get("analysis") or {}).get("fields", [])}
    out = []
    for f in discovery["profile"]["fields"]:
        info = meaning.get(f["name"], {})
        samples = f.get("all_values") or f.get("samples") or []
        base = {"meaning": info.get("meaning", ""), "format": info.get("format", ""),
                "role": info.get("role", ""), "is_phi": info.get("is_phi")}
        n = f.get("components", 1)
        if discovery["system"] == "hl7_feed" and n > 1 and f["name"] != "MSH-2":
            for i in range(n):
                comp = [s.split("^")[i] for s in samples if len(s.split("^")) > i and s.split("^")[i]]
                if comp:
                    out.append({"name": f"{f['name']}.{i + 1}", "samples": comp[:3], **base,
                                "meaning": f"{base['meaning']} (HL7 component {i + 1} of {n})"})
        else:
            out.append({"name": f["name"], "samples": samples[:3], **base})
    return out


def describe(field: dict) -> str:
    return f"{field['name']} {field['meaning']} {field['format']}"


# ------------------------------------------------------------- Stage 2: LLM re-rank
SYSTEM_PROMPT = """You are a senior HL7 FHIR R4 mapping engineer.
Map legacy healthcare fields to FHIR. Sample values are privacy-masked ('#' digits,
'***' letters) but formats are real. HL7 v2.5.1 standard field/component positions apply.
Reply with JSON only."""

TASK = """Source system: {system} ({kind})

For EACH field below choose exactly ONE target from the allowed list (copy the string
exactly), or "none" if the field should not be mapped (lookup tables, surrogate keys,
technical/message metadata). The ML candidates are hints; you may pick any allowed target.

Guidance:
- A patient id in a table/segment whose rows ARE patients -> Patient.identifier.value.
- A patient id on an encounter/diagnosis/lab row -> that resource's .subject reference.
- Describe the value transform needed (e.g. "YYYYMMDD -> YYYY-MM-DD", "1->male,2->female").
- confidence: 0.95+ only if certain; 0.6-0.8 if plausible but ambiguous; lower if guessing.

Allowed targets:
{targets}

Fields:
{fields}

Return: {{"mappings": [{{"source": "...", "target": "...", "transform": "...",
"confidence": 0.0, "reason": "one short sentence"}}]}}"""


def llm_rerank(system: str, kind: str, fields: list[dict], candidates: dict) -> dict:
    from agents.llm import ask_json
    payload = [{"name": f["name"], "meaning": f["meaning"], "format": f["format"],
                "masked_samples": f["samples"], "ml_candidates": candidates[f["name"]]} for f in fields]
    prompt = TASK.format(system=system, kind=kind, targets="\n".join(CATALOG),
                         fields=json.dumps(payload, indent=1))
    result = ask_json(prompt, system=SYSTEM_PROMPT, label=f"map:{system}")
    return {m.get("source"): m for m in result.get("mappings", [])}


# ------------------------------------------------------------- run
def map_system(discovery: dict, retriever: Retriever, use_llm: bool) -> dict:
    system = discovery["system"]
    fields = load_fields(discovery)
    t0 = time.perf_counter()
    candidates = {f["name"]: retriever.rank(describe(f)) for f in fields}
    t_ml = time.perf_counter() - t0

    llm, t_llm, model = {}, None, None
    if use_llm:
        from agents.llm import model_name
        print(f"[{system}] re-ranking {len(fields)} fields with {model_name()}...")
        t1 = time.perf_counter()
        llm = llm_rerank(system, discovery["profile"]["kind"], fields, candidates)
        t_llm, model = round(time.perf_counter() - t1, 2), model_name()

    mappings = []
    for f in fields:
        cands = candidates[f["name"]]
        ml_top, ml_score = cands[0]
        m = llm.get(f["name"])
        if m:
            target = m.get("target") or "none"
            valid = target in CATALOG
            ranks = [t for t, _ in cands]
            agreement = 1.0 if target == ml_top else (0.95 if target in ranks else 0.85)
            conf = round(float(m.get("confidence", 0)) * agreement, 3) if valid else 0.0
            transform, reason, source = m.get("transform", ""), m.get("reason", ""), "hybrid"
        else:  # ML only (no LLM, or the LLM skipped this field)
            target, valid, conf = ml_top, True, round(min(ml_score / 0.6, 1.0) * 0.75, 3)
            transform, reason, source = "", "ML retrieval only", "ml_only"
        mappings.append({
            "source": f["name"], "target": None if target == "none" else target,
            "transform": transform, "confidence": conf,
            "status": "auto_approved" if conf >= THRESHOLD and valid else "needs_review",
            "decided_by": source, "reason": reason, "valid_target": valid,
            "ml_top1": None if ml_top == "none" else ml_top, "ml_candidates": cands,
        })

    auto = sum(m["status"] == "auto_approved" for m in mappings)
    print(f"[{system}] {len(mappings)} fields | auto-approved {auto} | needs review {len(mappings) - auto}"
          + (f" | LLM {t_llm}s" if t_llm else ""))
    return {"system": system, "model": model, "threshold": THRESHOLD,
            "timing_seconds": {"ml": round(t_ml, 3), "llm": t_llm}, "mappings": mappings}


def write_report(results: list[dict]) -> Path:
    lines = ["# MedRelay - Mapping proposals", "",
             f"Confidence gate: >= {THRESHOLD} auto-approved, otherwise sent to a human.", ""]
    for r in results:
        lines += [f"## {r['system']}", "", "| Source | FHIR target | Transform | Conf. | Status |",
                  "|---|---|---|---|---|"]
        for m in r["mappings"]:
            flag = "OK" if m["status"] == "auto_approved" else "**REVIEW**"
            lines.append(f"| `{m['source']}` | `{m['target']}` | {m['transform']} | {m['confidence']} | {flag} |")
        lines.append("")
    path = OUT / "mapping_report.md"
    path.write_text("\n".join(lines))
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["legacy_db", "rest_api", "hl7_feed"])
    ap.add_argument("--no-llm", action="store_true", help="ML retrieval only (baseline)")
    args = ap.parse_args()

    files = sorted(f for f in DISC.glob("*.json") if f.name != "privacy.json")
    if not files:
        raise SystemExit("No discovery results found - run  python -m agents.discover  first")
    retriever = Retriever(CATALOG)
    OUT.mkdir(parents=True, exist_ok=True)
    results, failed = [], []
    discs = [json.loads(fp.read_text()) for fp in files]
    discs = [d for d in discs if not args.only or d["system"] == args.only]
    for d in discs:
        if not d.get("analysis"):
            print(f"[{d['system']}] note: no Discover analysis (was it run with --no-llm?) - using names only")
    with ThreadPoolExecutor(max_workers=3) as pool:   # the 3 systems are independent -> run together
        futures = {d["system"]: pool.submit(map_system, d, retriever, not args.no_llm) for d in discs}
    for system, fut in futures.items():
        try:
            res = fut.result()
        except Exception as e:
            print(f"[{system}] FAILED: {type(e).__name__}: {e}")
            failed.append(system)
            continue
        (OUT / f"{system}.json").write_text(json.dumps(res, indent=2))
        results.append(res)
    print(f"Report: {write_report(results)}")
    if failed:
        print(f"Not completed: {failed} - rerun with  python -m agents.map --only <system>")
        sys.exit(1)
    print("Next: python scripts/evaluate_mapping.py")
