"""
Step 1 - Generate the clean "source of truth" patient dataset.

Every mock system (legacy DB, REST API, HL7 feed) is built FROM this file,
each in its own messy format. Because we know the clean truth, we can later
measure how accurately the agents reconstruct it as FHIR.

Synthea-style but dependency-free (stdlib only), so it runs anywhere.
If you prefer real Synthea output, you can swap this file out later.

Usage:  python data/generate_data.py --patients 200 --seed 42
Output: data/truth.json
"""
import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

GIVEN_M = ["Sean", "Liam", "Conor", "Oisin", "Cian", "Darragh", "James", "Rohan", "Arjun", "Luca"]
GIVEN_F = ["Aoife", "Niamh", "Saoirse", "Ciara", "Emma", "Grace", "Priya", "Sofia", "Hannah", "Orla"]
FAMILY = ["Murphy", "Kelly", "O'Sullivan", "Walsh", "Byrne", "Ryan", "O'Brien", "Sharma",
          "Nowak", "Doyle", "McCarthy", "Gallagher", "Rossi", "Khan", "Lynch"]
CITIES = [("Dublin", "D04"), ("Cork", "T12"), ("Galway", "H91"), ("Limerick", "V94"), ("Waterford", "X91")]
STREETS = ["Main St", "Church Rd", "Station Rd", "Bridge St", "Park Ave", "Green Ln"]

# ICD-10 diagnoses
CONDITIONS = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10", "Essential (primary) hypertension"),
    ("J45.909", "Unspecified asthma, uncomplicated"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("J06.9", "Acute upper respiratory infection, unspecified"),
]
ENCOUNTER_TYPES = [("AMB", "ambulatory"), ("EMER", "emergency"), ("IMP", "inpatient encounter")]

# LOINC lab tests: code, display, unit, (low, high) plausible range, (ref_low, ref_high)
LABS = [
    ("2345-7", "Glucose [Mass/volume] in Serum or Plasma", "mg/dL", (70, 220), (70, 99)),
    ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", "%", (4.5, 10.5), (4.0, 5.6)),
    ("2093-3", "Cholesterol [Mass/volume] in Serum or Plasma", "mg/dL", (140, 290), (0, 200)),
    ("718-7", "Hemoglobin [Mass/volume] in Blood", "g/dL", (10.0, 17.5), (12.0, 17.5)),
    ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL", (0.5, 2.4), (0.6, 1.3)),
]


def rand_date(rng, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def generate(n_patients: int, seed: int) -> dict:
    rng = random.Random(seed)
    patients, encounters, conditions, observations = [], [], [], []
    today = date(2026, 11, 1)

    for i in range(1, n_patients + 1):
        gender = rng.choice(["male", "female", "female", "male", "unknown"] if i % 50 == 0 else ["male", "female"])
        given = rng.choice(GIVEN_F if gender == "female" else GIVEN_M)
        city, eircode_prefix = rng.choice(CITIES)
        pid = f"P{i:05d}"
        patients.append({
            "id": pid,
            "given": given,
            "family": rng.choice(FAMILY),
            "gender": gender,
            "birthDate": rand_date(rng, date(1940, 1, 1), date(2008, 12, 31)).isoformat(),
            "phone": f"+353 8{rng.randint(3, 9)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
            "line": f"{rng.randint(1, 120)} {rng.choice(STREETS)}",
            "city": city,
            "postalCode": f"{eircode_prefix} {rng.choice('ACDEFHKNPRTVWXY')}{rng.randint(100, 999)}",
            "country": "IE",
        })

        # Chronic conditions (0-2 per patient)
        patient_conditions = rng.sample(CONDITIONS, k=rng.choice([0, 1, 1, 2]))

        for _ in range(rng.randint(1, 4)):
            eid = f"E{len(encounters) + 1:06d}"
            etype = rng.choice(ENCOUNTER_TYPES)
            start = rand_date(rng, date(2023, 1, 1), today)
            los = 0 if etype[0] == "AMB" else rng.randint(0, 6)
            encounters.append({
                "id": eid, "patientId": pid, "classCode": etype[0], "classDisplay": etype[1],
                "start": start.isoformat(), "end": (start + timedelta(days=los)).isoformat(),
                "status": "finished",
            })
            dx_pool = patient_conditions or [rng.choice(CONDITIONS)]
            code, display = rng.choice(dx_pool)
            conditions.append({
                "id": f"C{len(conditions) + 1:06d}", "patientId": pid, "encounterId": eid,
                "code": code, "display": display, "onsetDate": start.isoformat(),
                "clinicalStatus": "active",
            })

        for _ in range(rng.randint(1, 3)):
            code, display, unit, (lo, hi), (rlo, rhi) = rng.choice(LABS)
            value = round(rng.uniform(lo, hi), 1)
            observations.append({
                "id": f"O{len(observations) + 1:06d}", "patientId": pid,
                "code": code, "display": display, "value": value, "unit": unit,
                "refLow": rlo, "refHigh": rhi,
                "interpretation": "H" if value > rhi else ("L" if value < rlo else "N"),
                "effectiveDateTime": f"{rand_date(rng, date(2024, 1, 1), today).isoformat()}T{rng.randint(7, 17):02d}:{rng.choice(['00', '15', '30', '45'])}:00",
                "status": "final",
            })

    return {"patients": patients, "encounters": encounters,
            "conditions": conditions, "observations": observations}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    truth = generate(args.patients, args.seed)
    out = Path(__file__).parent / "truth.json"
    out.write_text(json.dumps(truth, indent=2))
    print(f"Wrote {out}: " + ", ".join(f"{k}={len(v)}" for k, v in truth.items()))
