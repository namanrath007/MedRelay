"""
Tested helper functions the generated adapters are allowed to use.
Keeping conversions here (not re-invented by the LLM each time) makes the
generated code shorter, more consistent and easier to review.
"""
import hashlib
from datetime import datetime


def yyyymmdd_to_date(v):
    """'19600110' -> '1960-01-10'"""
    if not v:
        return None
    v = str(v).strip()
    return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"


def ddmmyyyy_to_date(v):
    """'10/01/1960' -> '1960-01-10'"""
    if not v:
        return None
    d, m, y = str(v).strip().split("/")
    return f"{y}-{m}-{d}"


def ts_to_datetime(v):
    """'20250314083000' or '202503140830' -> '2025-03-14T08:30:00'  (HL7 / legacy timestamps)"""
    if not v:
        return None
    v = str(v).strip()
    v = (v + "00")[:14] if len(v) == 12 else v
    return datetime.strptime(v[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%dT%H:%M:%S")


def title_case(v):
    """'O'SULLIVAN' -> 'O'Sullivan', '87 GREEN LN' -> '87 Green Ln'"""
    return str(v).strip().title() if v else None


def sentence_case(v):
    """'TYPE 2 DIABETES MELLITUS' -> 'Type 2 diabetes mellitus'"""
    if not v:
        return None
    s = str(v).strip().lower()
    return s[:1].upper() + s[1:]


def icd10_add_dot(v):
    """'E119' -> 'E11.9', 'I10' -> 'I10'"""
    if not v:
        return None
    v = str(v).strip().upper()
    return v if len(v) <= 3 or "." in v else f"{v[:3]}.{v[3:]}"


def code_map(value, mapping: dict, default=None):
    """Translate a local code: code_map('1', {'1': 'male', '2': 'female'}) -> 'male'"""
    return mapping.get(str(value).strip(), default) if value is not None else default


def to_decimal(v):
    if v is None or str(v).strip() == "":
        return None
    f = float(v)
    return int(f) if f.is_integer() and "." not in str(v) else f


def split_range(v):
    """'70-99' -> (70, 99);  '0.6-1.3' -> (0.6, 1.3)"""
    if not v or "-" not in str(v):
        return None, None
    lo, hi = str(v).split("-", 1)
    return to_decimal(lo), to_decimal(hi)


def ref(resource_type: str, rid) -> dict:
    """ref('Patient', '400001') -> {'reference': 'Patient/400001'}"""
    return {"reference": f"{resource_type}/{rid}"}


def stable_id(*parts) -> str:
    """Deterministic, PHI-free resource id from source keys."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# Standard FHIR code systems (so adapters don't misspell URLs)
SYS = {
    "mrn": "urn:fhirbridge:mrn",
    "portal": "urn:careportal:member",
    "icd10": "http://hl7.org/fhir/sid/icd-10",
    "loinc": "http://loinc.org",
    "ucum": "http://unitsofmeasure.org",
    "act_code": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "condition_clinical": "http://terminology.hl7.org/CodeSystem/condition-clinical",
    "obs_interp": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
}
