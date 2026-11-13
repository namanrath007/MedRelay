"""
Data layer for the patient-portal REST API (kept separate from FastAPI so it
can be tested without a web server).

The portal's shape is different again from the legacy DB:
  * member id 'MBR-xxxxxx' plus an 'extRef' field holding the legacy MRN
  * dob as 'DD/MM/YYYY', sex as 'M'/'F'/'U'
  * nested 'nm' and 'contact' objects, abbreviated keys
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mock_systems"))
from ids import to_member_id, to_mrn  # noqa: E402

SEX = {"male": "M", "female": "F", "unknown": "U"}


def _to_member(p: dict) -> dict:
    d = date.fromisoformat(p["birthDate"])
    return {
        "memberId": to_member_id(p["id"]),
        "extRef": to_mrn(p["id"]),
        "nm": {"first": p["given"], "last": p["family"]},
        "dob": d.strftime("%d/%m/%Y"),
        "sx": SEX[p["gender"]],
        "contact": {
            "mobile": p["phone"],
            "addr": {"street": p["line"], "town": p["city"], "eircode": p["postalCode"]},
        },
        "portalStatus": "ACTIVE",
    }


def load_members() -> list[dict]:
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    return [_to_member(p) for p in truth["patients"]]
