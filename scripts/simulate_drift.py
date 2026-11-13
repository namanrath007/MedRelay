"""
Simulate a real-world schema change in the legacy EHR (for the drift demo).

  python scripts/simulate_drift.py --apply    # rename PT_MSTR.PT_DOB_DT -> PT_BIRTH_DT
  python scripts/simulate_drift.py --reset    # rename it back
  python scripts/simulate_drift.py --status

Vendors rename columns during upgrades all the time; hand-built integrations
then break silently. MedRelay's drift agent detects and repairs this.
"""
import argparse
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db"
BACKUP = ROOT / "outputs" / "drift" / "backup"



def columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--reset", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--table", default="PT_MSTR")
    ap.add_argument("--old", default="PT_DOB_DT")
    ap.add_argument("--new", default="PT_BIRTH_DT")
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    cols = columns(con, a.table)
    if a.apply and a.old in cols:
        con.execute(f"ALTER TABLE {a.table} RENAME COLUMN {a.old} TO {a.new}")
        print(f"DRIFT APPLIED: {a.table}.{a.old} renamed to {a.table}.{a.new}")
    elif a.reset:
        if a.new in cols:
            con.execute(f"ALTER TABLE {a.table} RENAME COLUMN {a.new} TO {a.old}")
            print(f"RESET: {a.table}.{a.new} renamed back to {a.table}.{a.old}")
        if BACKUP.exists():  # undo an approved drift fix so the demo can be repeated
            shutil.copy(BACKUP / "legacy_db.py", ROOT / "generated" / "adapters" / "legacy_db.py")
            mapping_backup = BACKUP / "mapping_legacy_db.json"
            if mapping_backup.exists():
                shutil.copy(mapping_backup, ROOT / "outputs" / "mapping" / "legacy_db.json")
            shutil.copy(BACKUP / "discovery_legacy_db.json", ROOT / "outputs" / "discovery" / "legacy_db.json")
            shutil.rmtree(BACKUP)
            (ROOT / "outputs" / "drift" / "latest.json").unlink(missing_ok=True)
            print("RESET: adapter, mapping and discovery baseline restored")
    else:
        print(f"{a.table} columns: {columns(con, a.table)}")
    con.commit()
    con.close()
