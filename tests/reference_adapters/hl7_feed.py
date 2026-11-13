"""REFERENCE adapter (hand-written) - used only to test the Validate agent's checks."""
from fhirbridge_runtime.transforms import SYS, code_map, ref, split_range, title_case, to_decimal, ts_to_datetime, yyyymmdd_to_date


def to_fhir(entity, r):
    if entity != "ORU_R01":
        return []
    mrn = r["PID-3.1"]
    lo, hi = split_range(r.get("OBX-7"))
    patient = {"resourceType": "Patient", "id": mrn,
               "identifier": [{"system": SYS["mrn"], "value": mrn}],
               "name": [{"family": title_case(r.get("PID-5.1")), "given": [title_case(r.get("PID-5.2"))]}],
               "birthDate": yyyymmdd_to_date(r.get("PID-7")),
               "gender": code_map(r.get("PID-8"), {"M": "male", "F": "female", "U": "unknown"})}
    obs = {"resourceType": "Observation", "id": r["OBR-3"],
           "identifier": [{"value": r["OBR-3"]}],
           "status": code_map(r.get("OBX-11"), {"F": "final", "P": "preliminary"}, "unknown"),
           "code": {"coding": [{"system": SYS["loinc"], "code": r["OBX-3.1"], "display": r.get("OBX-3.2")}]},
           "subject": ref("Patient", mrn),
           "effectiveDateTime": ts_to_datetime(r.get("OBX-14")),
           "valueQuantity": {"value": to_decimal(r.get("OBX-5")), "unit": r.get("OBX-6"),
                             "system": SYS["ucum"], "code": r.get("OBX-6")},
           "referenceRange": [{"low": {"value": lo}, "high": {"value": hi}}],
           "interpretation": [{"coding": [{"system": SYS["obs_interp"], "code": r.get("OBX-8")}]}]}
    return [patient, obs]
