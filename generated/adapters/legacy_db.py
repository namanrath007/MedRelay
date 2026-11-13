import re
from fhirbridge_runtime.transforms import (
    SYS,
    code_map,
    icd10_add_dot,
    ref,
    stable_id,
    ts_to_datetime,
    yyyymmdd_to_date,
)


def _is_valid_id(val: str) -> bool:
    return bool(val and re.match(r"^[A-Za-z0-9-.]{1,64}$", str(val)))


def to_fhir(entity: str, record: dict) -> list[dict]:
    if not record:
        return []

    if entity == "PT_MSTR":
        pt_id = record.get("PT_MSTR.PT_ID")
        if not pt_id:
            return []

        res = {
            "resourceType": "Patient",
            "id": str(pt_id),
            "identifier": [{"system": SYS["mrn"], "value": str(pt_id)}],
        }

        gender = code_map(record.get("PT_MSTR.PT_SX_CD"), {"1": "male", "2": "female", "9": "other"})
        if gender:
            res["gender"] = gender

        bdate = yyyymmdd_to_date(record.get("PT_MSTR.PT_BIRTH_DT"))
        if bdate:
            res["birthDate"] = bdate

        lst_nm = record.get("PT_MSTR.PT_LST_NM")
        fst_nm = record.get("PT_MSTR.PT_FST_NM")
        if lst_nm or fst_nm:
            name_dict = {}
            if lst_nm:
                name_dict["family"] = lst_nm
            if fst_nm:
                name_dict["given"] = [fst_nm]
            res["name"] = [name_dict]

        addr1 = record.get("PT_MSTR.PT_ADR_1")
        city = record.get("PT_MSTR.PT_CTY")
        post = record.get("PT_MSTR.PT_PST_CD")
        country = record.get("PT_MSTR.PT_CNTRY")
        if any([addr1, city, post, country]):
            addr_dict = {}
            if addr1:
                addr_dict["line"] = [addr1]
            if city:
                addr_dict["city"] = city
            if post:
                addr_dict["postalCode"] = post
            if country:
                addr_dict["country"] = country
            res["address"] = [addr_dict]

        ph = record.get("PT_MSTR.PT_PH_NO")
        if ph:
            res["telecom"] = [{"system": "phone", "value": ph}]

        upd = record.get("PT_MSTR.REC_UPD_TS")
        if upd:
            dt_str = ts_to_datetime(upd)
            if dt_str:
                res["meta"] = {"lastUpdated": dt_str if dt_str.endswith("Z") else f"{dt_str}Z"}

        return [res]

    elif entity == "ENC_HDR":
        enc_id = record.get("ENC_HDR.ENC_ID")
        if not enc_id:
            return []

        res_id = str(enc_id) if _is_valid_id(str(enc_id)) else stable_id("Encounter", enc_id)
        res = {
            "resourceType": "Encounter",
            "id": res_id,
            "identifier": [{"value": str(enc_id)}],
        }

        stat = code_map(record.get("ENC_HDR.ENC_STAT"), {"C": "finished"})
        if stat:
            res["status"] = stat

        cls_code = code_map(record.get("ENC_HDR.ENC_TYP_CD"), {"OP": "AMB", "ED": "EMER", "IP": "IMP"})
        if cls_code:
            res["class"] = {"system": SYS["act_code"], "code": cls_code}

        pt_id = record.get("ENC_HDR.PT_ID")
        if pt_id:
            res["subject"] = ref("Patient", pt_id)

        adm_dt = yyyymmdd_to_date(record.get("ENC_HDR.ADM_DT"))
        dsch_dt = yyyymmdd_to_date(record.get("ENC_HDR.DSCH_DT"))
        if adm_dt or dsch_dt:
            period = {}
            if adm_dt:
                period["start"] = adm_dt
            if dsch_dt:
                period["end"] = dsch_dt
            res["period"] = period

        return [res]

    elif entity == "DX_DTL":
        dx_cd = record.get("DX_DTL.DX_CD")
        pt_id = record.get("DX_DTL.PT_ID")
        enc_id = record.get("DX_DTL.ENC_ID")
        seq = record.get("DX_DTL.DX_SEQ")

        cid = stable_id("Condition", pt_id, enc_id, seq, dx_cd)
        res = {
            "resourceType": "Condition",
            "id": cid,
        }

        if pt_id:
            res["subject"] = ref("Patient", pt_id)
        if enc_id:
            res["encounter"] = ref("Encounter", enc_id)

        cstat = code_map(record.get("DX_DTL.DX_STAT"), {"A": "active"})
        if cstat:
            res["clinicalStatus"] = {
                "coding": [{"system": SYS["condition_clinical"], "code": cstat}]
            }

        dx_dt = yyyymmdd_to_date(record.get("DX_DTL.DX_DT"))
        if dx_dt:
            res["onsetDateTime"] = dx_dt

        if dx_cd:
            code_val = icd10_add_dot(str(dx_cd))
            coding = {"system": SYS["icd10"], "code": code_val}
            desc = record.get("DX_DTL.DX_DESC")
            if desc:
                coding["display"] = desc
            res["code"] = {"coding": [coding]}

        return [res]

    return []
