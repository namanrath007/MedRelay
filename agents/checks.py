"""
The three checks the Validate agent runs on every generated adapter.

  1. security_scan(code)      static analysis (AST) - no I/O, network, logging, eval,
                              hard-coded secrets; only whitelisted imports.
                              Generated adapters must be PURE functions.
  2. fhir_structure(resource) FHIR R4 structural rules for Patient, Encounter,
                              Condition, Observation (required elements, data types,
                              value sets, reference format).
  3. fidelity(system, store)  compares produced FHIR with the known truth data,
                              field by field -> % of values reproduced correctly.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mock_systems"))

# ------------------------------------------------------------------ 1. security
ALLOWED_IMPORTS = {"re", "json", "math", "datetime", "decimal", "typing",
                   "fhirbridge_runtime", "fhirbridge_runtime.transforms"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "input", "print",
                   "globals", "locals", "getattr", "setattr", "delattr", "breakpoint"}
FORBIDDEN_ATTR_ROOTS = {"os", "sys", "subprocess", "socket", "requests", "urllib", "http",
                        "logging", "shutil", "pathlib", "pickle"}
SECRET_PATTERNS = [r"AIza[0-9A-Za-z_\-]{20,}", r"AQ\.[0-9A-Za-z_\-]{20,}",
                   r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]", r"demo-key"]


def security_scan(code: str) -> list[str]:
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error line {e.lineno}: {e.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    issues.append(f"line {node.lineno}: import '{a.name}' not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") not in ALLOWED_IMPORTS:
                issues.append(f"line {node.lineno}: import from '{node.module}' not allowed")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                issues.append(f"line {node.lineno}: call to '{fn.id}()' not allowed "
                              f"(adapters must not do I/O or log patient data)")
            if isinstance(fn, ast.Attribute):
                root = fn
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in FORBIDDEN_ATTR_ROOTS:
                    issues.append(f"line {node.lineno}: '{root.id}.*' calls not allowed")
    for pat in SECRET_PATTERNS:
        if re.search(pat, code):
            issues.append(f"possible hard-coded secret matching /{pat}/")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "to_fhir" for n in tree.body):
        issues.append("missing required function: to_fhir(entity, record)")
    return issues


# ------------------------------------------------------------------ 2. FHIR structure
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")
ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
REF = re.compile(r"^(Patient|Encounter|Condition|Observation)/[A-Za-z0-9\-.]{1,64}$")
GENDER = {"male", "female", "other", "unknown"}
ENC_STATUS = {"planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled",
              "entered-in-error", "unknown"}
OBS_STATUS = {"registered", "preliminary", "final", "amended", "corrected", "cancelled",
              "entered-in-error", "unknown"}


def _coding_ok(cc, where, errs, required=True):
    """CodeableConcept: {'coding': [{'system':..,'code':..}], 'text':..}"""
    if cc is None:
        if required:
            errs.append(f"{where} is required")
        return
    if not isinstance(cc, dict) or not isinstance(cc.get("coding", []), list):
        errs.append(f"{where} must be a CodeableConcept {{'coding': [...]}}")
        return
    for c in cc.get("coding", []):
        if not isinstance(c, dict) or not c.get("code"):
            errs.append(f"{where}.coding[] needs a 'code'")


def _ref_ok(r, where, errs, required=True):
    if r is None:
        if required:
            errs.append(f"{where} is required")
        return
    if not isinstance(r, dict) or not REF.match(str(r.get("reference", ""))):
        errs.append(f"{where} must look like {{'reference': 'Patient/<id>'}}")


def fhir_structure(res: dict) -> list[str]:
    errs = []
    if not isinstance(res, dict):
        return ["resource is not a JSON object"]
    rt = res.get("resourceType")
    if rt not in {"Patient", "Encounter", "Condition", "Observation"}:
        return [f"unsupported resourceType {rt!r}"]
    if not ID.match(str(res.get("id", ""))):
        errs.append(f"{rt}.id missing or invalid (1-64 chars A-Z a-z 0-9 - .)")
    for ident in (res.get("identifier") or []) if isinstance(res.get("identifier"), list) else []:
        if not isinstance(ident, dict) or not ident.get("value"):
            errs.append(f"{rt}.identifier[] needs a 'value'")
    if "identifier" in res and not isinstance(res["identifier"], list):
        errs.append(f"{rt}.identifier must be a list")

    if rt == "Patient":
        if res.get("gender") is not None and res["gender"] not in GENDER:
            errs.append(f"Patient.gender must be one of {sorted(GENDER)}")
        if res.get("birthDate") is not None and not DATE.match(str(res["birthDate"])):
            errs.append("Patient.birthDate must be YYYY-MM-DD")
        for key in ("name", "telecom", "address"):
            if key in res and not isinstance(res[key], list):
                errs.append(f"Patient.{key} must be a list")
        for n in [x for x in (res.get("name") or []) if isinstance(x, dict)] if isinstance(res.get("name"), list) else []:
            if "given" in n and not isinstance(n["given"], list):
                errs.append("Patient.name[].given must be a list of strings")
            if "family" in n and not isinstance(n["family"], str):
                errs.append("Patient.name[].family must be a string")
        for a in [x for x in (res.get("address") or []) if isinstance(x, dict)] if isinstance(res.get("address"), list) else []:
            if "line" in a and not isinstance(a["line"], list):
                errs.append("Patient.address[].line must be a list of strings")
        for t in [x if isinstance(x, dict) else {} for x in (res.get("telecom") or [])] if isinstance(res.get("telecom"), list) else []:
            if not t.get("value") or t.get("system") not in {"phone", "fax", "email", "pager", "url", "sms", "other"}:
                errs.append("Patient.telecom[] needs 'system' (e.g. phone) and 'value'")
        if "active" in res and not isinstance(res["active"], bool):
            errs.append("Patient.active must be true/false")

    elif rt == "Encounter":
        if res.get("status") not in ENC_STATUS:
            errs.append(f"Encounter.status is required, one of {sorted(ENC_STATUS)}")
        cls = res.get("class")
        if not isinstance(cls, dict) or not cls.get("code"):
            errs.append("Encounter.class is required and must be a Coding {'system','code'} (not a list)")
        _ref_ok(res.get("subject"), "Encounter.subject", errs)
        for k in ("start", "end"):
            v = _d(res.get("period")).get(k)
            if v is not None and not DATETIME.match(str(v)):
                errs.append(f"Encounter.period.{k} must be a FHIR dateTime")

    elif rt == "Condition":
        _ref_ok(res.get("subject"), "Condition.subject", errs)
        _ref_ok(res.get("encounter"), "Condition.encounter", errs, required=False)
        _coding_ok(res.get("code"), "Condition.code", errs)
        _coding_ok(res.get("clinicalStatus"), "Condition.clinicalStatus", errs, required=False)
        if res.get("onsetDateTime") is not None and not DATETIME.match(str(res["onsetDateTime"])):
            errs.append("Condition.onsetDateTime must be a FHIR dateTime")

    elif rt == "Observation":
        if res.get("status") not in OBS_STATUS:
            errs.append(f"Observation.status is required, one of {sorted(OBS_STATUS)}")
        _coding_ok(res.get("code"), "Observation.code", errs)
        _ref_ok(res.get("subject"), "Observation.subject", errs, required=False)
        vq = res.get("valueQuantity")
        if vq is not None and not isinstance(_d(vq).get("value"), (int, float)):
            errs.append("Observation.valueQuantity.value must be a number")
        rr = res.get("referenceRange")
        if rr is not None and not isinstance(rr, list):
            errs.append("Observation.referenceRange must be a list")
        interp = res.get("interpretation")
        if interp is not None and not isinstance(interp, list):
            errs.append("Observation.interpretation must be a list of CodeableConcepts")
        if res.get("effectiveDateTime") is not None and not DATETIME.match(str(res["effectiveDateTime"])):
            errs.append("Observation.effectiveDateTime must be a FHIR dateTime")
    return errs


# ------------------------------------------------------------------ 3. fidelity
def _d(x):
    """Defensive: treat anything that is not a dict as an empty dict (malformed AI output)."""
    return x if isinstance(x, dict) else {}


def _first(lst, key=None):
    if isinstance(lst, dict):
        lst = [lst]
    if not lst or not isinstance(lst, list):
        return None
    item = lst[0]
    return item.get(key) if key and isinstance(item, dict) else item


def _codes(cc):
    coding = _d(cc).get("coding", [])
    return {c.get("code") for c in (coding if isinstance(coding, list) else []) if isinstance(c, dict)}


def _norm(v):
    return None if v is None else str(v).strip().lower().replace(" ", "")


def _num(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _subject_id(res, key="subject"):
    return str(_d(res.get(key)).get("reference", "")).split("/")[-1]


def fidelity(system: str, resources: list[dict], truth: dict) -> dict:
    """Field-by-field comparison with the truth data. Names are compared case-insensitively
    because the legacy source only stores UPPERCASE (information genuinely lost upstream)."""
    from ids import to_mrn
    pts = {to_mrn(p["id"]): p for p in truth["patients"]}
    by_type = {}
    for r in resources:
        by_type.setdefault(r.get("resourceType"), []).append(r)
    checks, fails = 0, []

    def check(label, got, exp, rid):
        nonlocal checks
        checks += 1
        if got != exp:
            fails.append({"check": label, "resource": rid, "expected": exp, "got": got})

    # Patients (every system carries some demographics)
    for p in by_type.get("Patient", []):
        t = pts.get(str(p.get("id")))
        if t is None:
            fails.append({"check": "Patient.id is the MRN", "resource": p.get("id"),
                          "expected": "an MRN like 400001", "got": p.get("id")})
            checks += 1
            continue
        name = _d(_first(p.get("name")))
        check("Patient.name.family", _norm(name.get("family")), _norm(t["family"]), p["id"])
        check("Patient.name.given", _norm(_first(name.get("given"))), _norm(t["given"]), p["id"])
        check("Patient.birthDate", p.get("birthDate"), t["birthDate"], p["id"])
        check("Patient.gender", p.get("gender"), t["gender"], p["id"])
        if system in ("legacy_db", "rest_api"):
            check("Patient.telecom.value", _norm(_first(p.get("telecom"), "value")), _norm(t["phone"]), p["id"])
            addr = _d(_first(p.get("address")))
            check("Patient.address.city", _norm(addr.get("city")), _norm(t["city"]), p["id"])
            check("Patient.address.postalCode", _norm(addr.get("postalCode")), _norm(t["postalCode"]), p["id"])
            check("Patient.address.line", _norm(_first(addr.get("line"))), _norm(t["line"]), p["id"])

    if system == "legacy_db":
        enc = {e["id"].replace("E", "V"): e for e in truth["encounters"]}
        found = {}
        for e in by_type.get("Encounter", []):
            ids = {e.get("id")} | {_d(i).get("value") for i in (e.get("identifier") or []) if isinstance(e.get("identifier"), list)}
            key = next((i for i in ids if i in enc), None)
            if key is None:
                fails.append({"check": "Encounter identifier", "resource": e.get("id"),
                              "expected": "source ENC_ID (V000123)", "got": list(ids)})
                checks += 1
                continue
            t = enc[key]
            found[key] = e
            check("Encounter.class.code", _d(e.get("class")).get("code"), t["classCode"], key)
            check("Encounter.period.start", str(_d(e.get("period")).get("start", ""))[:10], t["start"], key)
            check("Encounter.period.end", str(_d(e.get("period")).get("end", ""))[:10], t["end"], key)
            check("Encounter.status", e.get("status"), "finished", key)
            check("Encounter.subject", _subject_id(e), to_mrn(t["patientId"]), key)
        check("Encounter count", len(found), len(enc), "all")
        conds = by_type.get("Condition", [])
        check("Condition count", len(conds), len(truth["conditions"]), "all")
        tc = {}
        for c in truth["conditions"]:
            tc.setdefault((c["encounterId"].replace("E", "V"), c["code"]), c)
        for c in conds:
            codes = _codes(c.get("code"))
            enc_id = _subject_id(c, "encounter")
            match = next((tc[(enc_id, code)] for code in codes if (enc_id, code) in tc), None)
            if match is None:
                # encounter reference may use a hashed id - fall back to patient + code + date
                match = next((t for t in truth["conditions"]
                              if to_mrn(t["patientId"]) == _subject_id(c) and t["code"] in codes
                              and str(c.get("onsetDateTime", ""))[:10] == t["onsetDate"]), None)
            if match is None:
                fails.append({"check": "Condition matches a true diagnosis (code+encounter)", "resource": c.get("id"),
                              "expected": "ICD-10 code with dot, e.g. E11.9", "got": sorted(codes)})
                checks += 1
                continue
            check("Condition.subject", _subject_id(c), to_mrn(match["patientId"]), c.get("id"))
            check("Condition.onsetDateTime", str(c.get("onsetDateTime", ""))[:10], match["onsetDate"], c.get("id"))
            check("Condition.clinicalStatus", sorted(_codes(c.get("clinicalStatus"))), ["active"], c.get("id"))

    if system == "hl7_feed":
        obs = by_type.get("Observation", [])
        check("Observation count", len(obs), len(truth["observations"]), "all")
        to = {o["id"]: o for o in truth["observations"]}
        for o in obs:
            ids = {o.get("id")} | {_d(i).get("value") for i in (o.get("identifier") or []) if isinstance(o.get("identifier"), list)}
            key = next((i for i in ids if i in to), None)
            if key is None:
                fails.append({"check": "Observation identifier", "resource": o.get("id"),
                              "expected": "OBR-3 order id (O000123)", "got": list(ids)})
                checks += 1
                continue
            t = to[key]
            vq = _d(o.get("valueQuantity"))
            check("Observation.code", sorted(_codes(o.get("code"))), [t["code"]], key)
            check("Observation.valueQuantity.value", _num(vq.get("value")), _num(t["value"]), key)
            check("Observation.valueQuantity.unit", vq.get("unit") or vq.get("code"), t["unit"], key)
            check("Observation.interpretation", sorted(set().union(*[_codes(i) for i in (o.get("interpretation") if isinstance(o.get("interpretation"), list) else [])]) or []),
                  [t["interpretation"]], key)
            check("Observation.effectiveDateTime", str(o.get("effectiveDateTime", ""))[:19], t["effectiveDateTime"], key)
            check("Observation.status", o.get("status"), "final", key)
            check("Observation.subject", _subject_id(o), to_mrn(t["patientId"]), key)
            rr = _d(_first(o.get("referenceRange")))
            check("Observation.referenceRange", (_num(_d(rr.get("low")).get("value")), _num(_d(rr.get("high")).get("value"))),
                  (_num(t["refLow"]), _num(t["refHigh"])), key)

    passed = checks - len(fails)
    return {"checks": checks, "passed": passed,
            "fidelity_pct": round(100 * passed / checks, 2) if checks else 0.0,
            "failures": fails}
