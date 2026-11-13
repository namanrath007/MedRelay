from fhirbridge_runtime.transforms import (
    SYS,
    code_map,
    ddmmyyyy_to_date,
)


def to_fhir(entity: str, record: dict) -> list[dict]:
    if entity != "member":
        return []

    patient_id = record.get("extRef") or record.get("memberId")
    patient = {
        "resourceType": "Patient",
        "id": patient_id,
    }

    identifiers = []
    if record.get("memberId"):
        identifiers.append({"system": SYS["portal"], "value": record["memberId"]})
    if record.get("extRef"):
        identifiers.append({"system": SYS["mrn"], "value": record["extRef"]})
    if identifiers:
        patient["identifier"] = identifiers

    if record.get("portalStatus") is not None:
        patient["active"] = record.get("portalStatus") == "ACTIVE"

    first_name = record.get("nm.first")
    last_name = record.get("nm.last")
    if first_name or last_name:
        name_obj = {}
        if last_name:
            name_obj["family"] = last_name
        if first_name:
            name_obj["given"] = [first_name]
        patient["name"] = [name_obj]

    mobile = record.get("contact.mobile")
    if mobile:
        patient["telecom"] = [{"system": "phone", "value": mobile, "use": "mobile"}]

    gender = code_map(record.get("sx"), {"F": "female", "M": "male"})
    if gender:
        patient["gender"] = gender

    birth_date = ddmmyyyy_to_date(record.get("dob"))
    if birth_date:
        patient["birthDate"] = birth_date

    street = record.get("contact.addr.street")
    town = record.get("contact.addr.town")
    eircode = record.get("contact.addr.eircode")
    if street or town or eircode:
        addr = {}
        if street:
            addr["line"] = [street]
        if town:
            addr["city"] = town
        if eircode:
            addr["postalCode"] = eircode
        patient["address"] = [addr]

    return [patient]
