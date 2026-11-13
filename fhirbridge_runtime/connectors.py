"""
Source connectors: read each system and yield FLAT records whose keys are exactly
the source-field names used by the Discover and Map agents.

  legacy_db  ("PT_MSTR", {"PT_MSTR.PT_ID": "400001", "PT_MSTR.PT_DOB_DT": "19600110", ...})
  rest_api   ("member",  {"memberId": "MBR-007919", "nm.first": "Sean", ...})
  hl7_feed   ("ORU_R01", {"PID-3": "400001^^^LEGACYEHR^MR", "PID-3.1": "400001", "PID-5.1": "WALSH", ...})

Generated adapters never touch databases, HTTP or files - they only receive these
records. That keeps AI-written code small, pure and safe to test.
"""
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

from fhirbridge_runtime import env  # noqa: F401  (loads .env)

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "legacy_db": ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db",
    "rest_api": os.getenv("PORTAL_BASE_URL", "http://localhost:8001"),
    "hl7_feed": ROOT / "mock_systems" / "hl7_feed" / "outbox",
}


def iter_legacy(db_path=None):
    con = sqlite3.connect(db_path or DEFAULTS["legacy_db"])
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        for row in con.execute(f"SELECT * FROM {t}"):
            yield t, {f"{t}.{k}": row[k] for k in row.keys()}
    con.close()


def _flatten(obj, prefix=""):
    out = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        out.update(_flatten(v, key) if isinstance(v, dict) else {key: v})
    return out


def iter_rest(base_url=None, api_key=None, page_size=100):
    base_url = base_url or DEFAULTS["rest_api"]
    api_key = api_key or os.getenv("PORTAL_API_KEY", "demo-key")
    page = 1
    while True:
        req = urllib.request.Request(f"{base_url}/api/v1/members?page={page}&size={page_size}",
                                     headers={"X-API-Key": api_key})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for item in data["items"]:
            yield "member", _flatten(item)
        if page * page_size >= data["total"]:
            break
        page += 1


def parse_hl7(text: str) -> dict:
    """HL7 v2 message -> {"PID-5": "WALSH^SEAN", "PID-5.1": "WALSH", "PID-5.2": "SEAN", ...}.
    MSH is special: MSH-1 is the field separator itself. First occurrence of a segment wins."""
    rec = {}
    for seg in text.split("\r"):
        if not seg:
            continue
        parts = seg.split("|")
        name, offset = parts[0], (1 if parts[0] == "MSH" else 0)
        for i, value in enumerate(parts[1:], start=1):
            key = f"{name}-{i + offset}"
            if key in rec or value == "":
                continue
            rec[key] = value
            if "^" in value and name != "MSH":
                for j, comp in enumerate(value.split("^"), start=1):
                    if comp:
                        rec[f"{key}.{j}"] = comp
    return rec


def iter_hl7(folder=None):
    for fp in sorted(Path(folder or DEFAULTS["hl7_feed"]).glob("*.hl7")):
        # read bytes: HL7 segments end in \r and Python's text mode would rewrite them
        yield "ORU_R01", parse_hl7(fp.read_bytes().decode("ascii", "replace"))


def iter_source(system: str):
    return {"legacy_db": iter_legacy, "rest_api": iter_rest, "hl7_feed": iter_hl7}[system]()


ENTITIES = {"legacy_db": ["PT_MSTR", "ENC_HDR", "DX_DTL", "REF_CD"],
            "rest_api": ["member"], "hl7_feed": ["ORU_R01"]}
