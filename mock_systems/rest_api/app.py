"""
Step 3 - Mock system #2: a cloud patient-portal REST API (FastAPI).

Run:   uvicorn mock_systems.rest_api.app:app --port 8001 --reload
Docs:  http://localhost:8001/docs        (Swagger UI)
Spec:  http://localhost:8001/openapi.json  <- the Discover agent reads this
Auth:  header  X-API-Key: demo-key
"""
import os

from fhirbridge_runtime import env  # noqa: F401  (loads .env)

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from mock_systems.rest_api.members_store import load_members

API_KEY = os.getenv("PORTAL_API_KEY", "demo-key")

app = FastAPI(
    title="CarePortal Member API",
    version="1.3.0",
    description="Patient-portal member records (mock system for MedRelay).",
)

MEMBERS = load_members()
BY_ID = {m["memberId"]: m for m in MEMBERS}


def require_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/health")
def health():
    return {"status": "ok", "members": len(MEMBERS)}


@app.get("/api/v1/members", dependencies=[Depends(require_key)])
def list_members(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    start = (page - 1) * size
    return {"page": page, "size": size, "total": len(MEMBERS), "items": MEMBERS[start:start + size]}


@app.get("/api/v1/members/{member_id}", dependencies=[Depends(require_key)])
def get_member(member_id: str):
    if member_id not in BY_ID:
        raise HTTPException(status_code=404, detail="member not found")
    return BY_ID[member_id]
