import re
from fhirbridge_runtime.transforms import (
    SYS,
    code_map,
    ref,
    split_range,
    stable_id,
    to_decimal,
    ts_to_datetime,
    yyyymmdd_to_date,
)

def _is_valid_id(val: str) -> bool:
    return bool(val and 1 <= len(val) <= 64 and re.match(r'^[A-Za-z0-9-.]+$', val))

def to_fhir(entity: str, record: dict) -> list[dict]:
    if entity != "ORU_R01":
        return []

    resources = []
    mrn = record.get("PID-3.1")
    
    if mrn:
        patient = {
            "resourceType": "Patient",
            "id": mrn,
            "identifier": [{"system": SYS["mrn"], "value": mrn}],
        }
        
        family = record.get("PID-5.1")
        given = record.get("PID-5.2")
        name_dict = {}
        if family:
            name_dict["family"] = family
        if given:
            name_dict["given"] = [given]
        if name_dict:
            patient["name"] = [name_dict]
            
        dob = record.get("PID-7")
        if dob:
            patient["birthDate"] = yyyymmdd_to_date(dob)
            
        gender = record.get("PID-8")
        if gender:
            mapped_gender = code_map(gender, {"F": "female", "M": "male"}, default="unknown")
            if mapped_gender:
                patient["gender"] = mapped_gender
                
        resources.append(patient)

    obs_raw_id = record.get("OBR-3")
    code_val = record.get("OBX-3.1") or record.get("OBR-4.1")
    obs_id = obs_raw_id if (obs_raw_id and _is_valid_id(obs_raw_id)) else stable_id("Observation", mrn, obs_raw_id, code_val)
    
    obs = {
        "resourceType": "Observation",
        "id": obs_id,
        "status": code_map(record.get("OBX-11"), {"F": "final", "C": "corrected", "P": "preliminary"}, default="final"),
    }
    
    if obs_raw_id:
        obs["identifier"] = [{"value": obs_raw_id}]
        
    if mrn:
        obs["subject"] = ref("Patient", mrn)
        
    display_val = record.get("OBX-3.2") or record.get("OBR-4.2")
    if code_val:
        coding = {"system": SYS["loinc"], "code": code_val}
        if display_val:
            coding["display"] = display_val
        obs["code"] = {"coding": [coding]}
        
    eff_dt = record.get("OBX-14") or record.get("OBR-7")
    if eff_dt:
        obs["effectiveDateTime"] = ts_to_datetime(eff_dt)
        
    val_num = to_decimal(record.get("OBX-5"))
    unit = record.get("OBX-6")
    if val_num is not None:
        vq = {"value": val_num}
        if unit:
            vq["unit"] = unit
        obs["valueQuantity"] = vq
        
    ref_str = record.get("OBX-7")
    if ref_str:
        low, high = split_range(ref_str)
        rr = {}
        if low is not None:
            rr["low"] = {"value": low, "unit": unit} if unit else {"value": low}
        if high is not None:
            rr["high"] = {"value": high, "unit": unit} if unit else {"value": high}
        if rr:
            obs["referenceRange"] = [rr]
            
    interp_raw = record.get("OBX-8")
    if interp_raw:
        interp_code = code_map(interp_raw, {"H": "H", "L": "L", "N": "N"})
        if interp_code:
            obs["interpretation"] = [{
                "coding": [{
                    "system": SYS["obs_interp"],
                    "code": interp_code
                }]
            }]

    resources.append(obs)
    return resources
