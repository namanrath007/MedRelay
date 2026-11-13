"""
Build everything in one go:  python scripts/build_all.py [--patients 200] [--seed 42]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mock_systems"))

from data.generate_data import generate  # noqa: E402
from mock_systems.legacy_db.build_legacy_db import build as build_db  # noqa: E402
from mock_systems.hl7_feed.build_hl7_feed import build as build_hl7  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--hard", action="store_true", help="hard mode: strip schema comments (no doc hints)")
    args = ap.parse_args()

    truth = generate(args.patients, args.seed)
    (ROOT / "data" / "truth.json").write_text(json.dumps(truth, indent=2))
    print("[1/3] truth.json: " + ", ".join(f"{k}={len(v)}" for k, v in truth.items()))
    print("[2/3] ", end=""); build_db(truth, ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db", hard=args.hard)
    print("[3/3] ", end=""); build_hl7(truth, ROOT / "mock_systems" / "hl7_feed" / "outbox")
    print("Done. Start the REST API with:  uvicorn mock_systems.rest_api.app:app --port 8001")
