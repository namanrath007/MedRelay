"""
The unified FHIR R4 API - one standard interface over all integrated systems.

Run:   python -m uvicorn fhir_api.app:app --port 8002
Docs:  http://localhost:8002/docs
Auth:  header  X-API-Key: <FHIR_API_KEY from .env, default fhir-demo-key>

Examples:
  GET /fhir/Patient/400001
  GET /fhir/Patient/400001/$everything        <- data from all 3 systems in one bundle
  GET /fhir/Observation?subject=Patient/400001
  GET /fhir/Patient?identifier=MBR-007919
"""
import os

from fhirbridge_runtime import env  # noqa: F401  (loads .env)

from fastapi import Depends, FastAPI, Header, HTTPException

from fhir_api.store import bundle, everything, load_store, search, stats

API_KEY = os.getenv("FHIR_API_KEY", "fhir-demo-key")
TYPES = {"Patient", "Encounter", "Condition", "Observation"}
app = FastAPI(title="MedRelay unified FHIR R4 API", version="1.0.0")


def require_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")


def _store():
    return load_store()  # re-read each request so newly published adapters show up immediately


@app.get("/fhir/metadata")
def metadata():
    s = _store()
    return {"resourceType": "CapabilityStatement", "status": "active", "fhirVersion": "4.0.1",
            "format": ["json"], "rest": [{"mode": "server", "resource": [
                {"type": t, "interaction": [{"code": "read"}, {"code": "search-type"}]} for t in sorted(TYPES)]}],
            "_fhirbridge_stats": stats(s)}


@app.get("/fhir/Patient/{pid}/$everything", dependencies=[Depends(require_key)])
def patient_everything(pid: str):
    b = everything(_store(), pid)
    if b is None:
        raise HTTPException(404, "Patient not found")
    return b


@app.get("/fhir/{rtype}", dependencies=[Depends(require_key)])
def search_type(rtype: str, subject: str | None = None, identifier: str | None = None,
                code: str | None = None, _count: int = 50):
    if rtype not in TYPES:
        raise HTTPException(404, f"unsupported resource type {rtype}")
    return bundle(search(_store(), rtype, subject, identifier, code)[:_count])


@app.get("/fhir/{rtype}/{rid}", dependencies=[Depends(require_key)])
def read(rtype: str, rid: str):
    r = _store().get(rtype, {}).get(rid)
    if r is None:
        raise HTTPException(404, f"{rtype}/{rid} not found")
    return r
