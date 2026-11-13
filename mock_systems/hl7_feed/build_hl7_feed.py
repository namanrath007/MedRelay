"""
Step 4 - Mock system #3: a lab-system HL7 v2.5.1 flat-file feed.

Writes one ORU^R01 (observation result) message per lab result into ./outbox,
the way many lab instruments / interface engines drop files today.

Segment cheat-sheet (fields separated by |, components by ^):
  MSH  message header      - sender, timestamp, message type, control id
  PID  patient identity    - PID-3 = MRN^^^LEGACYEHR^MR  (links to the legacy DB!)
  OBR  order request       - test ordered, observation time
  OBX  observation result  - LOINC code, value, unit, reference range, H/L/N flag, status

Usage:  python mock_systems/hl7_feed/build_hl7_feed.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mock_systems"))
from ids import to_mrn  # noqa: E402

SEX = {"male": "M", "female": "F", "unknown": "U"}


def hl7_ts(iso: str) -> str:
    return iso.replace("-", "").replace(":", "").replace("T", "")


def build_message(n: int, obs: dict, patient: dict) -> str:
    ts = hl7_ts(obs["effectiveDateTime"])
    ref = f"{obs['refLow']}-{obs['refHigh']}"
    segments = [
        f"MSH|^~\\&|LABSYS|UCDLAB|FHIRBRIDGE|HOSP|{ts}||ORU^R01|MSG{n:06d}|P|2.5.1",
        f"PID|1||{to_mrn(patient['id'])}^^^LEGACYEHR^MR||{patient['family'].upper()}^{patient['given'].upper()}"
        f"||{hl7_ts(patient['birthDate'])}|{SEX[patient['gender']]}",
        f"OBR|1||{obs['id']}|{obs['code']}^{obs['display']}^LN|||{ts}",
        f"OBX|1|NM|{obs['code']}^{obs['display']}^LN||{obs['value']}|{obs['unit']}|{ref}"
        f"|{obs['interpretation']}|||F|||{ts}",
    ]
    return "\r".join(segments) + "\r"  # HL7 v2 segment terminator is carriage return


def build(truth: dict, outbox: Path) -> None:
    shutil.rmtree(outbox, ignore_errors=True)
    outbox.mkdir(parents=True)
    patients = {p["id"]: p for p in truth["patients"]}
    for n, obs in enumerate(truth["observations"], start=1):
        msg = build_message(n, obs, patients[obs["patientId"]])
        (outbox / f"ORU_{n:06d}.hl7").write_bytes(msg.encode("ascii", errors="replace"))
    print(f"Wrote {len(truth['observations'])} HL7 messages to {outbox}")


if __name__ == "__main__":
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    build(truth, Path(__file__).parent / "outbox")
