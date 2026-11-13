"""Load fhirbridge/.env into os.environ (no extra library needed). Safe to call many times."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env(warn: bool = False):
    if not ENV_FILE.exists():
        if warn:
            print(f"WARNING: no .env file at {ENV_FILE} (copy .env.example to .env)")
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
