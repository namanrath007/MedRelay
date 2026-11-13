# MedRelay - Discovery report

Generated 2026-11-12 17:40 | status: **pending human review**

Privacy: sample values masked before any LLM call -> {'identifier': 31, 'name': 15, 'date': 28, 'address': 11, 'postal_code': 6, 'phone': 6}

## legacy_db  (relational database (SQLite))

This legacy relational database (SQLite) acts as a basic Electronic Health Record (EHR) system. It stores patient demographics, administrative encounter headers, clinical diagnosis details, and local reference lookup codes.

- **Patient identifier:** `PT_MSTR.PT_ID` - Unique patient identifier used across patient, encounter, and diagnosis tables acting as the primary key/MRN.
- **Link keys:** `PT_MSTR.PT_ID` -> Enterprise Patient Identifier or MRN
- **Integration pattern:** database_cdc - Direct SQLite relational database integration where incremental data extraction can be performed by polling modified records via PT_MSTR.REC_UPD_TS.
- **Coverage:** 27/27 fields
- **Time:** profile 0.01s + LLM 132.79s

| Field | Meaning | Format | PHI |
|---|---|---|---|
| `PT_MSTR.PT_ID` | Primary patient identifier (MRN) | numeric text (6 digits) | identifier |
| `PT_MSTR.PT_LST_NM` | Patient last name | free text | name |
| `PT_MSTR.PT_FST_NM` | Patient first name | free text | name |
| `PT_MSTR.PT_SX_CD` | Patient sex code | code list 1/2/9 |  |
| `PT_MSTR.PT_BIRTH_DT` | Patient date of birth | YYYYMMDD | date_of_birth |
| `PT_MSTR.PT_ADR_1` | Patient street address line 1 | free text | address |
| `PT_MSTR.PT_CTY` | Patient city | free text |  |
| `PT_MSTR.PT_PST_CD` | Patient postal code / Eircode | alphanumeric (e.g. H91 ****) | postal_code |
| `PT_MSTR.PT_CNTRY` | Patient country | ISO 3166-1 alpha-3 (e.g. IRL) |  |
| `PT_MSTR.PT_PH_NO` | Patient contact phone number | E.164 phone number format | phone |
| `PT_MSTR.REC_UPD_TS` | Record update timestamp | YYYYMMDDHHMMSS (14 digits) |  |
| `ENC_HDR.ENC_ID` | Primary key for encounter record | alphanumeric ID (e.g. V00##01) |  |
| `ENC_HDR.PT_ID` | Foreign key referencing PT_MSTR.PT_ID | numeric text (6 digits) | identifier |
| `ENC_HDR.ENC_TYP_CD` | Encounter class code | code list OP/ED/IP |  |
| `ENC_HDR.ADM_DT` | Encounter admission date | YYYYMMDD |  |
| `ENC_HDR.DSCH_DT` | Encounter discharge date | YYYYMMDD |  |
| `ENC_HDR.ENC_STAT` | Encounter status code | single-character code (C) |  |
| `DX_DTL.DX_SEQ` | Primary key sequence for diagnosis details | autoincrement integer |  |
| `DX_DTL.ENC_ID` | Foreign key referencing ENC_HDR.ENC_ID | alphanumeric ID |  |
| `DX_DTL.PT_ID` | Patient identifier for diagnosis record | numeric text (6 digits) | identifier |
| `DX_DTL.DX_CD` | ICD-10 diagnosis code | ICD-10 without decimal dots (e.g. E119) |  |
| `DX_DTL.DX_DESC` | Human-readable diagnosis description | free text |  |
| `DX_DTL.DX_DT` | Date diagnosis was recorded | YYYYMMDD |  |
| `DX_DTL.DX_STAT` | Diagnosis clinical status | single-character code (A) |  |
| `REF_CD.CD_TYP` | Reference code classification group | code list (ENC, STAT, SX) |  |
| `REF_CD.CD_VAL` | Reference code key value | alphanumeric code |  |
| `REF_CD.CD_DESC` | Description of reference code | free text |  |

**Data quality notes**
- ICD-10 codes in DX_DTL.DX_CD lack standard decimal dot notation (e.g., 'E119' instead of 'E11.9') and require reformatting for standard terminology servers.
- Dates (PT_BIRTH_DT, ADM_DT, DSCH_DT, DX_DT) are stored as 8-digit strings (YYYYMMDD) without time or timezone components.
- Sex, encounter types, and status fields rely on internal codes requiring ConceptMap translation using REF_CD lookup data to map to FHIR code systems.
- ENC_HDR and DX_DTL lack explicit updated timestamp fields, complicating change data capture for non-patient records.

**Risks**
- Concurrency issues and file-locking risks associated with direct database polling against an active SQLite file.
- Missing time components on admission/discharge dates can lead to inaccurate encounter duration calculations in FHIR.
- Lack of updated timestamps on Encounter and Diagnosis tables risks missed updates unless full tables are regularly scanned.

## hl7_feed  (HL7 v2 flat-file feed)

This system is an HL7 v2.5.1 flat-file feed emitting ORU^R01 unsolicited observation result messages. It carries patient demographics alongside laboratory test results, including LOINC-coded observations such as cholesterol, glucose, creatinine, and hemoglobin.

- **Patient identifier:** `PID-3` - Composite field containing the patient medical record number (MRN) and assigning authority (e.g., 40##01^^^LEGACYEHR^MR).
- **Link keys:** `PID-3` -> Patient.identifier (MRN), `OBR-3` -> ServiceRequest.identifier or DiagnosticReport.identifier (Filler Order Number)
- **Integration pattern:** batch_file_ingest - The source system outputs flat-file HL7 feeds into a directory outbox path requiring scheduled or event-driven file ingestion.
- **Coverage:** 28/28 fields
- **Time:** profile 0.03s + LLM 140.56s

| Field | Meaning | Format | PHI |
|---|---|---|---|
| `MSH-2` | Encoding characters delimiter definition | delimiter string (^~\&) |  |
| `MSH-3` | Sending application identifier | text code |  |
| `MSH-4` | Sending facility identifier | text code |  |
| `MSH-5` | Receiving application identifier | text code |  |
| `MSH-6` | Receiving facility identifier | text code |  |
| `MSH-7` | Message date and time | YYYYMMDDHHMMSS |  |
| `MSH-9` | Message type and trigger event | HL7 message type (ORU^R01) |  |
| `MSH-10` | Message control ID for tracking and deduplication | text identifier |  |
| `MSH-11` | Processing ID code | code list (P=Production) |  |
| `MSH-12` | HL7 version identifier | version string (2.5.1) |  |
| `PID-1` | Set ID - PID sequence counter | integer string |  |
| `PID-3` | Patient identifier list containing MRN and assigning authority | ID^^^AssigningAuthority^IdentifierType | identifier |
| `PID-5` | Patient legal name | Surname^GivenName | name |
| `PID-7` | Patient date of birth | YYYYMMDD | date_of_birth |
| `PID-8` | Administrative sex | HL7 Table 0001 (F, M) |  |
| `OBR-1` | Set ID - OBR sequence counter | integer string |  |
| `OBR-3` | Filler order number (lab order ID) | text identifier |  |
| `OBR-4` | Universal service identifier (ordered lab test code) | LOINC^Display^LN |  |
| `OBR-7` | Observation / specimen collection date and time | YYYYMMDDHHMMSS |  |
| `OBX-1` | Set ID - OBX sequence counter | integer string |  |
| `OBX-2` | Value type identifier | HL7 Table 0125 (NM=Numeric) |  |
| `OBX-3` | Observation identifier (LOINC test code) | LOINC^Display^LN |  |
| `OBX-5` | Numeric observation result value | numeric string |  |
| `OBX-6` | Units of measure | unit string (%, g/dL, mg/dL) |  |
| `OBX-7` | Reference range for the observation | range string (min-max) |  |
| `OBX-8` | Abnormal flags | HL7 Table 0078 (H, L, N) |  |
| `OBX-11` | Observation result status | HL7 Table 0085 (F=Final) |  |
| `OBX-14` | Date/time of the observation/analysis | YYYYMMDDHHMMSS |  |

**Data quality notes**
- HL7 v2 composite fields (PID-3, PID-5, OBR-4, OBX-3) require parsing component delimiters ('^').
- Timestamps (MSH-7, OBR-7, OBX-14) and date of birth (PID-7) use unformatted HL7 string representations (YYYYMMDD / YYYYMMDDHHMMSS) lacking explicit time zone offsets.
- OBX-7 reference ranges are provided as hyphenated strings (e.g., '70-99') that must be parsed into high/low numeric components for FHIR Observation.referenceRange.
- PID-8 administrative sex codes ('M', 'F') must be mapped to FHIR AdministrativeGender code system ('male', 'female').
- OBX-8 interpretation codes ('H', 'L', 'N') must be mapped to FHIR Observation Interpretation concept codes.

**Risks**
- Unencrypted flat files containing PHI stored in a file directory require strict operating system file-access controls and disk encryption.
- File drop processing lacks built-in network application-level acknowledgments (HL7 ACK), creating risk of silent processing failures or lost files if not moved to an archive/error folder safely.
- Potential risk of duplicate message ingestion if message control IDs (MSH-10) are not persistently tracked.
