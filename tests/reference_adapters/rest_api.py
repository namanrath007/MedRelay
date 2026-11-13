"""REFERENCE adapter (hand-written) - used only to test the Validate agent's checks."""
from fhirbridge_runtime.transforms import SYS, code_map, ddmmyyyy_to_date


def to_fhir(entity, r):
    if entity != "member":
        return []
    return [{
        "resourceType": "Patient", "id": r["extRef"],
        "identifier": [{"system": SYS["mrn"], "value": r["extRef"]},
                       {"system": SYS["portal"], "value": r["memberId"]}],
        "active": r.get("portalStatus") == "ACTIVE",
        "name": [{"family": r["nm.last"], "given": [r["nm.first"]]}],
        "gender": code_map(r["sx"], {"M": "male", "F": "female", "U": "unknown"}),
        "birthDate": ddmmyyyy_to_date(r["dob"]),
        "telecom": [{"system": "phone", "use": "mobile", "value": r["contact.mobile"]}],
        "address": [{"line": [r["contact.addr.street"]], "city": r["contact.addr.town"],
                     "postalCode": r["contact.addr.eircode"]}],
    }]
