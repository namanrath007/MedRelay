"""
The unified FHIR store: merges what each validated adapter published into one view.

Patients appear in several systems under the same id (the MRN), so they are MERGED:
identifiers are combined, other elements keep the first non-empty value in source
priority order (legacy EHR > patient portal > lab feed), and meta.tag records which
systems contributed - full provenance for every patient.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "outputs" / "fhir_store"
PRIORITY = ["legacy_db", "rest_api", "hl7_feed"]


def _merge_patient(base: dict, new: dict, system: str) -> dict:
    ids = {(i.get("system"), i.get("value")) for i in base.get("identifier", [])}
    for i in new.get("identifier", []) or []:
        if (i.get("system"), i.get("value")) not in ids:
            base.setdefault("identifier", []).append(i)
    for k, v in new.items():
        if k not in ("identifier", "meta") and v not in (None, [], {}, "") and base.get(k) in (None, [], {}, ""):
            base[k] = v
    meta = base.setdefault("meta", {})
    if (new.get("meta") or {}).get("lastUpdated") and "lastUpdated" not in meta:
        meta["lastUpdated"] = new["meta"]["lastUpdated"]
    tags = meta.setdefault("tag", [])
    if not any(t.get("code") == system for t in tags):
        tags.append({"system": "urn:fhirbridge:source-system", "code": system})
    return base


def load_store() -> dict:
    """-> {resourceType: {id: resource}}"""
    store = {}
    for system in PRIORITY:
        fp = STORE / f"{system}.json"
        if not fp.exists():
            continue
        for r in json.loads(fp.read_text()):
            rt, rid = r.get("resourceType"), str(r.get("id"))
            bucket = store.setdefault(rt, {})
            if rt == "Patient":
                bucket[rid] = _merge_patient(bucket.get(rid, {"resourceType": "Patient", "id": rid}), r, system)
            else:
                r.setdefault("meta", {})["tag"] = [{"system": "urn:fhirbridge:source-system", "code": system}]
                bucket[rid] = r
    return store


def search(store: dict, rtype: str, subject: str | None = None, identifier: str | None = None,
           code: str | None = None) -> list[dict]:
    out = list(store.get(rtype, {}).values())
    if subject:
        ref = subject if "/" in subject else f"Patient/{subject}"
        out = [r for r in out if (r.get("subject") or {}).get("reference") == ref]
    if identifier:
        value = identifier.split("|")[-1]
        out = [r for r in out if any(i.get("value") == value for i in r.get("identifier", []) or [])]
    if code:
        out = [r for r in out if any(c.get("code") == code for c in (r.get("code") or {}).get("coding", []))]
    return out


def bundle(resources: list[dict], btype: str = "searchset") -> dict:
    return {"resourceType": "Bundle", "type": btype, "total": len(resources),
            "entry": [{"fullUrl": f"{r['resourceType']}/{r['id']}", "resource": r} for r in resources]}


def everything(store: dict, patient_id: str) -> dict | None:
    """Patient/$everything: the patient plus every resource that references them."""
    p = store.get("Patient", {}).get(patient_id)
    if p is None:
        return None
    related = [r for rt in ("Encounter", "Condition", "Observation") for r in search(store, rt, subject=patient_id)]
    return bundle([p] + related, "searchset")


def stats(store: dict) -> dict:
    out = {rt: len(v) for rt, v in store.items()}
    pts = store.get("Patient", {}).values()
    out["patients_in_3_systems"] = sum(1 for p in pts if len(p.get("meta", {}).get("tag", [])) == 3)
    return out
