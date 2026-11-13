"""REFERENCE adapter (hand-written) - used only to test the Validate agent's checks."""
from fhirbridge_runtime.transforms import (SYS, code_map, icd10_add_dot, ref, sentence_case,
                                           stable_id, title_case, ts_to_datetime, yyyymmdd_to_date)


def to_fhir(entity, r):
    if entity == "PT_MSTR":
        mrn = r["PT_MSTR.PT_ID"]
        return [{
            "resourceType": "Patient", "id": mrn,
            "meta": {"lastUpdated": ts_to_datetime(r["PT_MSTR.REC_UPD_TS"])},
            "identifier": [{"system": SYS["mrn"], "value": mrn}],
            "name": [{"family": title_case(r["PT_MSTR.PT_LST_NM"]), "given": [title_case(r["PT_MSTR.PT_FST_NM"])]}],
            "gender": code_map(r["PT_MSTR.PT_SX_CD"], {"1": "male", "2": "female", "9": "unknown"}),
            "birthDate": yyyymmdd_to_date(r["PT_MSTR.PT_DOB_DT"]),
            "telecom": [{"system": "phone", "value": r["PT_MSTR.PT_PH_NO"]}],
            "address": [{"line": [title_case(r["PT_MSTR.PT_ADR_1"])], "city": title_case(r["PT_MSTR.PT_CTY"]),
                         "postalCode": r["PT_MSTR.PT_PST_CD"],
                         "country": code_map(r["PT_MSTR.PT_CNTRY"], {"IRL": "IE"}, r["PT_MSTR.PT_CNTRY"])}],
        }]
    if entity == "ENC_HDR":
        cls = code_map(r["ENC_HDR.ENC_TYP_CD"], {"OP": "AMB", "ED": "EMER", "IP": "IMP"})
        return [{
            "resourceType": "Encounter", "id": r["ENC_HDR.ENC_ID"],
            "identifier": [{"value": r["ENC_HDR.ENC_ID"]}],
            "status": code_map(r["ENC_HDR.ENC_STAT"], {"C": "finished"}, "unknown"),
            "class": {"system": SYS["act_code"], "code": cls},
            "subject": ref("Patient", r["ENC_HDR.PT_ID"]),
            "period": {"start": yyyymmdd_to_date(r["ENC_HDR.ADM_DT"]), "end": yyyymmdd_to_date(r["ENC_HDR.DSCH_DT"])},
        }]
    if entity == "DX_DTL":
        return [{
            "resourceType": "Condition", "id": stable_id("dx", r["DX_DTL.DX_SEQ"]),
            "subject": ref("Patient", r["DX_DTL.PT_ID"]),
            "encounter": ref("Encounter", r["DX_DTL.ENC_ID"]),
            "code": {"coding": [{"system": SYS["icd10"], "code": icd10_add_dot(r["DX_DTL.DX_CD"]),
                                 "display": sentence_case(r["DX_DTL.DX_DESC"])}]},
            "clinicalStatus": {"coding": [{"system": SYS["condition_clinical"],
                                           "code": code_map(r["DX_DTL.DX_STAT"], {"A": "active"})}]},
            "onsetDateTime": yyyymmdd_to_date(r["DX_DTL.DX_DT"]),
        }]
    return []
