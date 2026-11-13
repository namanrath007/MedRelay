"""
Deterministic profilers: read a system and describe its structure.
No AI here - just facts (names, types, counts, distinct values, masked samples).
The LLM later interprets these facts.

Every profiler returns the same shape:
  {"system": ..., "kind": ..., "fields": [ {name, type, samples, distinct, ...} ], "docs": ...}
"""
import json
import os
import sqlite3
import urllib.request
from collections import defaultdict
from pathlib import Path

from agents.privacy import mask_value

N_SAMPLES = 3       # sample values per field sent to the LLM
LOW_CARD = 12       # if a field has <= this many distinct values, list them all (codes!)


# ---------------------------------------------------------------- SQLite
def profile_sqlite(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    fields, ddl, entities = [], {}, []
    for t in tables:
        ddl[t] = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]
        rows = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        fks = {r[3]: f"{r[2]}.{r[4]}" for r in con.execute(f"PRAGMA foreign_key_list({t})")}
        entities.append({"name": t, "rows": rows, "foreign_keys": fks})
        for _, col, ctype, _, _, pk in con.execute(f"PRAGMA table_info({t})"):
            distinct = con.execute(f"SELECT COUNT(DISTINCT {col}) FROM {t}").fetchone()[0]
            name = f"{t}.{col}"
            f = {"name": name, "type": ctype, "primary_key": bool(pk), "distinct": distinct,
                 "nulls": con.execute(f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL").fetchone()[0]}
            if col in fks:
                f["references"] = fks[col]
            if distinct <= LOW_CARD:
                f["all_values"] = [mask_value(name, r[0]) for r in
                                   con.execute(f"SELECT DISTINCT {col} FROM {t} ORDER BY 1")]
            else:
                f["samples"] = [mask_value(name, r[0]) for r in
                                con.execute(f"SELECT {col} FROM {t} LIMIT {N_SAMPLES}")]
            fields.append(f)
    con.close()
    return {"system": "legacy_db", "kind": "relational database (SQLite)", "location": str(db_path),
            "entities": entities, "fields": fields, "docs": {"ddl": ddl}}


# ---------------------------------------------------------------- REST / OpenAPI
def _get_json(url: str, api_key: str | None = None):
    req = urllib.request.Request(url, headers={"X-API-Key": api_key} if api_key else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _flatten(obj, prefix=""):
    """{'nm': {'first': 'Sean'}} -> {'nm.first': 'Sean'}"""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def profile_rest(base_url: str, api_key: str | None = None) -> dict:
    api_key = api_key or os.getenv("PORTAL_API_KEY", "demo-key")
    spec = _get_json(f"{base_url}/openapi.json")
    paths = {p: list(ops.keys()) for p, ops in spec.get("paths", {}).items()}
    security = {p: [prm["name"] for op in ops.values() for prm in op.get("parameters", [])
                    if prm.get("in") == "header"] for p, ops in spec.get("paths", {}).items()}

    # Find the collection endpoint (no {param}) and pull one page of real records
    list_path = next(p for p in paths if "{" not in p and p.startswith("/api"))
    page = _get_json(f"{base_url}{list_path}?page=1&size=50", api_key)
    items = page.get("items", page if isinstance(page, list) else [])
    flat = [_flatten(i) for i in items]

    fields = []
    for key in flat[0]:
        values = [r.get(key) for r in flat]
        distinct = sorted({str(v) for v in values})
        f = {"name": key, "type": type(values[0]).__name__, "distinct_in_sample": len(distinct)}
        if len(distinct) <= LOW_CARD:
            f["all_values"] = [mask_value(key, v) for v in distinct]
        else:
            f["samples"] = [mask_value(key, v) for v in values[:N_SAMPLES]]
        fields.append(f)

    return {"system": "rest_api", "kind": "REST API (OpenAPI)", "location": base_url,
            "entities": [{"name": list_path, "rows": page.get("total", len(items)),
                          "pagination": [k for k in ("page", "size", "total") if k in page]}],
            "fields": fields,
            "docs": {"title": spec.get("info", {}).get("title"),
                     "description": spec.get("info", {}).get("description"),
                     "paths": paths, "header_params": security}}


# ---------------------------------------------------------------- HL7 v2
def _hl7_fields(segment: str):
    """Yield (field_id, value). MSH is special: MSH-1 is the '|' separator itself."""
    parts = segment.split("|")
    seg = parts[0]
    offset = 1 if seg == "MSH" else 0
    for i, value in enumerate(parts[1:], start=1):
        if value:
            yield f"{seg}-{i + offset}", value


def profile_hl7(folder: Path, max_files: int = 100) -> dict:
    files = sorted(folder.glob("*.hl7"))
    values = defaultdict(list)
    msg_types = set()
    for fp in files[:max_files]:
        # NB: HL7 segments end with \r - read bytes so Python doesn't rewrite them
        for seg in fp.read_bytes().decode("ascii", "replace").split("\r"):
            if not seg:
                continue
            for fid, val in _hl7_fields(seg):
                values[fid].append(val)
                if fid == "MSH-9":
                    msg_types.add(val)

    fields = []
    for fid, vals in values.items():
        distinct = sorted(set(vals))
        f = {"name": fid, "components": vals[0].count("^") + 1, "distinct_in_sample": len(distinct)}
        if len(distinct) <= LOW_CARD:
            f["all_values"] = [mask_value(fid, v) for v in distinct]
        else:
            f["samples"] = [mask_value(fid, v) for v in vals[:N_SAMPLES]]
        fields.append(f)

    return {"system": "hl7_feed", "kind": "HL7 v2 flat-file feed", "location": str(folder),
            "entities": [{"name": "messages", "rows": len(files), "message_types": sorted(msg_types),
                          "profiled": min(len(files), max_files)}],
            "fields": fields, "docs": {"encoding": "segments separated by \\r, fields by |, components by ^"}}
