"""
Step 2 - Mock system #1: a legacy on-prem EHR database (SQLite).

Deliberately "legacy-ugly", to give the Discover and Map agents real work:
  * cryptic table/column names   (PT_MSTR, PT_DOB_DT, ENC_TYP_CD, DX_CD ...)
  * dates stored as TEXT 'YYYYMMDD'
  * sex stored as numeric codes  1=male 2=female 9=unknown
  * names UPPERCASE, phone with no spaces
  * its own patient id (MRN), not the truth id
  * a code lookup table (REF_CD) the agent has to discover and join

Usage:  python mock_systems/legacy_db/build_legacy_db.py
Output: mock_systems/legacy_db/legacy_ehr.db
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mock_systems"))
from ids import to_mrn  # noqa: E402

SEX_CODE = {"male": "1", "female": "2", "unknown": "9"}
ENC_CODE = {"AMB": "OP", "EMER": "ED", "IMP": "IP"}  # legacy local codes

SCHEMA = """
CREATE TABLE PT_MSTR (            -- patient master
    PT_ID       TEXT PRIMARY KEY, -- MRN
    PT_LST_NM   TEXT,
    PT_FST_NM   TEXT,
    PT_SX_CD    TEXT,             -- 1/2/9, see REF_CD
    PT_DOB_DT   TEXT,             -- YYYYMMDD
    PT_ADR_1    TEXT,
    PT_CTY      TEXT,
    PT_PST_CD   TEXT,
    PT_CNTRY    TEXT,
    PT_PH_NO    TEXT,
    REC_UPD_TS  TEXT
);
CREATE TABLE ENC_HDR (            -- encounter header
    ENC_ID      TEXT PRIMARY KEY,
    PT_ID       TEXT REFERENCES PT_MSTR(PT_ID),
    ENC_TYP_CD  TEXT,             -- OP/ED/IP, see REF_CD
    ADM_DT      TEXT,             -- YYYYMMDD
    DSCH_DT     TEXT,             -- YYYYMMDD
    ENC_STAT    TEXT              -- C = complete
);
CREATE TABLE DX_DTL (             -- diagnosis detail
    DX_SEQ      INTEGER PRIMARY KEY AUTOINCREMENT,
    ENC_ID      TEXT REFERENCES ENC_HDR(ENC_ID),
    PT_ID       TEXT,
    DX_CD       TEXT,             -- ICD-10, no dot (E119)
    DX_DESC     TEXT,
    DX_DT       TEXT,             -- YYYYMMDD
    DX_STAT     TEXT              -- A = active
);
CREATE TABLE REF_CD (             -- local code lookup
    CD_TYP  TEXT,
    CD_VAL  TEXT,
    CD_DESC TEXT
);
"""


def yyyymmdd(iso: str) -> str:
    return iso.replace("-", "")


def build(truth: dict, out_path: Path, hard: bool = False) -> None:
    """hard=True strips the schema comments, so agents get NO documentation hints."""
    out_path.unlink(missing_ok=True)
    con = sqlite3.connect(out_path)
    schema = "\n".join(line.split("--")[0].rstrip() for line in SCHEMA.splitlines()) if hard else SCHEMA
    con.executescript(schema)

    con.executemany("INSERT INTO REF_CD VALUES (?,?,?)", [
        ("SX", "1", "MALE"), ("SX", "2", "FEMALE"), ("SX", "9", "UNKNOWN"),
        ("ENC", "OP", "OUTPATIENT"), ("ENC", "ED", "EMERGENCY DEPT"), ("ENC", "IP", "INPATIENT"),
        ("STAT", "C", "COMPLETE"), ("STAT", "A", "ACTIVE"),
    ])

    con.executemany("INSERT INTO PT_MSTR VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (to_mrn(p["id"]), p["family"].upper(), p["given"].upper(), SEX_CODE[p["gender"]],
         yyyymmdd(p["birthDate"]), p["line"].upper(), p["city"].upper(), p["postalCode"],
         "IRL", p["phone"].replace(" ", ""), "20261101093000")
        for p in truth["patients"]
    ])

    con.executemany("INSERT INTO ENC_HDR VALUES (?,?,?,?,?,?)", [
        (e["id"].replace("E", "V"), to_mrn(e["patientId"]), ENC_CODE[e["classCode"]],
         yyyymmdd(e["start"]), yyyymmdd(e["end"]), "C")
        for e in truth["encounters"]
    ])

    con.executemany(
        "INSERT INTO DX_DTL (ENC_ID, PT_ID, DX_CD, DX_DESC, DX_DT, DX_STAT) VALUES (?,?,?,?,?,?)", [
            (c["encounterId"].replace("E", "V"), to_mrn(c["patientId"]), c["code"].replace(".", ""),
             c["display"].upper(), yyyymmdd(c["onsetDate"]), "A")
            for c in truth["conditions"]
        ])

    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("PT_MSTR", "ENC_HDR", "DX_DTL", "REF_CD")}
    con.close()
    print(f"Wrote {out_path}: {counts}")


if __name__ == "__main__":
    truth = json.loads((ROOT / "data" / "truth.json").read_text())
    build(truth, Path(__file__).parent / "legacy_ehr.db")
