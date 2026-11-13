"""
Smoke test: proves the three systems are consistent with the truth data and
that one patient can be linked across all three via the MRN.

Usage:  python scripts/smoke_test.py
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mock_systems"))
from ids import to_mrn  # noqa: E402
from mock_systems.rest_api.members_store import load_members  # noqa: E402

truth = json.loads((ROOT / "data" / "truth.json").read_text())
db = sqlite3.connect(ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db")
outbox = ROOT / "mock_systems" / "hl7_feed" / "outbox"
members = load_members()

checks = {
    "legacy patients == truth": db.execute("SELECT COUNT(*) FROM PT_MSTR").fetchone()[0] == len(truth["patients"]),
    "legacy encounters == truth": db.execute("SELECT COUNT(*) FROM ENC_HDR").fetchone()[0] == len(truth["encounters"]),
    "legacy diagnoses == truth": db.execute("SELECT COUNT(*) FROM DX_DTL").fetchone()[0] == len(truth["conditions"]),
    "portal members == truth": len(members) == len(truth["patients"]),
    "hl7 messages == truth obs": len(list(outbox.glob("*.hl7"))) == len(truth["observations"]),
}

# Cross-system link for the first patient that has a lab result
obs = truth["observations"][0]
mrn = to_mrn(obs["patientId"])
row = db.execute("SELECT PT_FST_NM, PT_LST_NM, PT_DOB_DT FROM PT_MSTR WHERE PT_ID=?", (mrn,)).fetchone()
member = next(m for m in members if m["extRef"] == mrn)
pid = next(seg for seg in (outbox / "ORU_000001.hl7").read_bytes().decode("ascii").split("\r") if seg.startswith("PID"))
checks["MRN links DB <-> portal <-> HL7"] = (
    row is not None and member["nm"]["first"].upper() == row[0] and pid.split("|")[3].startswith(mrn)
)

print(f"\nPatient {obs['patientId']} seen three ways:")
print(f"  legacy DB : PT_ID={mrn}  {row}")
print(f"  portal API: memberId={member['memberId']}  extRef={member['extRef']}  dob={member['dob']}")
print(f"  HL7 feed  : {pid}\n")

for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
sys.exit(0 if all(checks.values()) else 1)
