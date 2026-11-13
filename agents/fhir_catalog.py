"""
The FHIR R4 target vocabulary the Map agent chooses from.

Each entry: target path -> plain-English description used for retrieval.
Includes realistic DISTRACTORS (deceasedDateTime, maritalStatus, ...) that no
source field should map to, so a lucky guesser can't score well, and "none"
for fields that should not be mapped at all (lookup tables, surrogate keys,
message metadata).
"""

CATALOG = {
    # Patient
    "Patient.identifier.value": "patient identifier id medical record number mrn member id external reference patient key",
    "Patient.name.family": "patient last name surname family name",
    "Patient.name.given": "patient first name given name forename",
    "Patient.gender": "patient sex gender administrative gender male female unknown code",
    "Patient.birthDate": "patient date of birth dob birth date born",
    "Patient.address.line": "patient street address line house number road",
    "Patient.address.city": "patient city town",
    "Patient.address.postalCode": "patient postal code postcode zip eircode",
    "Patient.address.country": "patient country nation code",
    "Patient.telecom.value": "patient phone telephone mobile number contact",
    "Patient.active": "patient record active status flag enabled portal status",
    "Patient.meta.lastUpdated": "record last updated timestamp modified update time",
    "Patient.deceasedDateTime": "patient date of death deceased died",
    "Patient.maritalStatus": "patient marital status married single",
    "Patient.communication.language": "patient preferred language spoken",
    # Encounter
    "Encounter.identifier.value": "encounter visit id identifier admission number",
    "Encounter.subject": "encounter patient reference which patient the visit belongs to",
    "Encounter.class": "encounter type class inpatient outpatient emergency ambulatory setting",
    "Encounter.period.start": "encounter admission start date admit date visit start",
    "Encounter.period.end": "encounter discharge end date visit end",
    "Encounter.status": "encounter visit status complete finished",
    "Encounter.location": "encounter ward room bed location",
    # Condition
    "Condition.subject": "diagnosis condition patient reference which patient has the diagnosis",
    "Condition.encounter": "diagnosis condition encounter visit reference recorded during visit",
    "Condition.code.coding.code": "diagnosis condition code icd-10 icd code",
    "Condition.code.coding.display": "diagnosis condition description name text display",
    "Condition.onsetDateTime": "diagnosis condition onset date diagnosed date",
    "Condition.clinicalStatus": "diagnosis condition clinical status active resolved",
    "Condition.severity": "diagnosis condition severity mild severe",
    # Observation (labs)
    "Observation.identifier.value": "lab observation result order id filler number identifier",
    "Observation.subject": "lab observation result patient reference which patient the result belongs to",
    "Observation.code.coding.code": "lab test code loinc observation identifier code",
    "Observation.code.coding.display": "lab test name description display text",
    "Observation.valueQuantity.value": "lab result numeric value measurement",
    "Observation.valueQuantity.unit": "lab result unit of measure units",
    "Observation.referenceRange": "lab reference range normal range low high",
    "Observation.interpretation": "lab abnormal flag interpretation high low normal",
    "Observation.status": "lab result status final preliminary",
    "Observation.effectiveDateTime": "lab observation date time collected effective specimen time",
    "Observation.issued": "lab result issued released report time",
    "Observation.category": "lab observation category laboratory vital signs",
    # Not mapped
    "none": "no fhir target lookup reference table code description sequence surrogate key "
            "message header control id sending application facility version set id value type",
}

# Abbreviations common in legacy healthcare schemas / HL7, expanded before retrieval
ABBREVIATIONS = {
    "pt": "patient", "pat": "patient", "mstr": "master", "id": "identifier", "nm": "name",
    "lst": "last", "fst": "first", "sx": "sex", "cd": "code", "dob": "date of birth",
    "dt": "date", "adr": "address", "addr": "address", "cty": "city", "pst": "postal",
    "cntry": "country", "ph": "phone", "no": "number", "rec": "record", "upd": "updated",
    "ts": "timestamp", "enc": "encounter", "hdr": "header", "typ": "type", "adm": "admission",
    "dsch": "discharge", "stat": "status", "dx": "diagnosis", "dtl": "detail", "seq": "sequence",
    "desc": "description", "ref": "reference", "val": "value", "sx_cd": "sex code",
    "dob_dt": "date of birth", "ext": "external", "mbr": "member", "sx.": "sex",
    "eircode": "eircode postal code", "mobile": "mobile phone",
}
