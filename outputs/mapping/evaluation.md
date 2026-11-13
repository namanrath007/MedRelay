# MedRelay - Mapping evaluation

| Metric | Value |
|---|---|
| fields_scored | 53 |
| ml_baseline_accuracy_pct | 75.5 |
| fhirbridge_accuracy_pct | 98.1 |
| auto_approved_pct_of_fields | 98.1 |
| auto_approved_precision_pct | 100.0 |
| sent_to_human_review | 0 |
| correctly_left_unmapped | 5/5 |

| System | Scored | ML baseline | MedRelay | Auto-approved (precision) | Needs review |
|---|---|---|---|---|---|
| legacy_db | 27 | 59.3% | 96.3% | 26 (100.0%) | 0 |
| rest_api | 11 | 100.0% | 100.0% | 11 (100.0%) | 0 |
| hl7_feed | 15 | 86.7% | 100.0% | 15 (100.0%) | 0 |

## Errors
- legacy_db `PT_MSTR.PT_DOB_DT`: expected `Patient.birthDate`, got `MISSING`