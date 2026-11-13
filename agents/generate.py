"""
GENERATE AGENT - step 3 of the MedRelay pipeline.

Turns the APPROVED field mappings for one system into a Python adapter:

    def to_fhir(entity: str, record: dict) -> list[dict]   # FHIR R4 resources

The adapter is pure: connectors (fhirbridge_runtime/connectors.py) feed it records,
and it may only use tested helpers from fhirbridge_runtime/transforms.py.
The Validate agent then tests it and, if anything fails, sends the errors back
here for another attempt (self-healing loop, see agents/validate.py).

Only mappings with status auto_approved / approved are used. Fields still
"needs_review" are NOT mapped until a human approves them in the dashboard.
"""
import inspect
import json
from pathlib import Path

from agents.privacy import mask_value
from fhirbridge_runtime import transforms
from fhirbridge_runtime.connectors import ENTITIES, iter_source

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "outputs" / "mapping"

SYSTEM_PROMPT = """You are a senior healthcare integration engineer who writes clean,
correct, minimal Python that converts source records into HL7 FHIR R4 JSON.
Sample values are privacy-masked ('#' digits, '***' letters) - formats are real.
Reply with JSON only: {"code": "<full python module>", "notes": "<1-3 sentences>"}"""

CONVENTIONS = """Conventions (must follow):
- Define exactly: def to_fhir(entity: str, record: dict) -> list[dict]
  It receives ONE record of type `entity` and returns a list of FHIR resources (dicts),
  or [] for entities that produce nothing (e.g. lookup tables).
- record keys are EXACTLY the source field names in the mapping table.
- Patient.id MUST be the MRN (the medical record number link key). Every reference to a
  patient is {"reference": "Patient/<MRN>"} - use ref("Patient", mrn).
- Other resources: id = the source's own identifier if it is 1-64 chars of [A-Za-z0-9-.],
  otherwise stable_id(<source keys>). Also put that source identifier in .identifier[].value.
- Lists where FHIR requires lists: name, name.given, telecom, address, address.line,
  identifier, referenceRange, interpretation. Encounter.class is a single Coding dict.
- Coded elements use CodeableConcept {"coding": [{"system": SYS[...], "code": ..., "display": ...}]}.
- Translate local codes to FHIR codes (gender male/female/unknown, Encounter.status finished,
  Encounter.class AMB/EMER/IMP from v3-ActCode, clinicalStatus active, Observation.status final,
  interpretation H/L/N).
- Dates YYYY-MM-DD; date-times YYYY-MM-DDThh:mm:ss.
- Only import from fhirbridge_runtime.transforms (and re/json/datetime/math if needed).
- NO print, logging, file/network access, eval/exec, or hard-coded secrets. Never raise
  on a missing optional field - use record.get(...).
- Keep it short and readable; a reviewer will read it."""


def helper_docs() -> str:
    lines = []
    for name, fn in inspect.getmembers(transforms, inspect.isfunction):
        if fn.__module__ == transforms.__name__:
            doc = (inspect.getdoc(fn) or "").splitlines()[0] if inspect.getdoc(fn) else ""
            lines.append(f"  {name}{inspect.signature(fn)}  # {doc}")
    lines.append(f"  SYS = {json.dumps(transforms.SYS, indent=None)}")
    return "\n".join(lines)


def approved_mappings(system: str) -> tuple[list[dict], list[str]]:
    data = json.loads((MAPPING / f"{system}.json").read_text())
    approved = [m for m in data["mappings"] if m["status"] in ("auto_approved", "approved")]
    pending = [m["source"] for m in data["mappings"] if m["status"] not in ("auto_approved", "approved")]
    return approved, pending


def example_records(system: str) -> dict:
    """One masked example per entity type, so the model sees real keys and formats."""
    examples = {}
    for entity, rec in iter_source(system):
        if entity not in examples:
            examples[entity] = {k: mask_value(k, v) for k, v in rec.items()}
        if len(examples) == len(ENTITIES[system]):
            break
    return examples


def build_prompt(system: str, previous_code: str | None = None, feedback: str | None = None) -> str:
    approved, pending = approved_mappings(system)
    table = [{"source": m["source"], "target": m["target"], "transform": m["transform"]} for m in approved]
    parts = [
        f"Write the FHIR adapter for source system '{system}'.",
        f"Entity types this system produces: {ENTITIES[system]}",
        "", CONVENTIONS, "",
        "Helpers available (from fhirbridge_runtime.transforms import ...):", helper_docs(), "",
        "APPROVED mappings (target null = do not map):", json.dumps(table, indent=1), "",
        "One masked example record per entity:", json.dumps(example_records(system), indent=1),
    ]
    if pending:
        parts += ["", f"Fields pending human review - do NOT map them yet: {pending}"]
    if previous_code and feedback:
        parts += ["", "Your previous attempt FAILED validation. Fix every problem below and return the",
                  "complete corrected module.", "", "VALIDATION FEEDBACK:", feedback, "",
                  "PREVIOUS CODE:", previous_code]
    return "\n".join(parts)


def generate_code(system: str, previous_code: str | None = None, feedback: str | None = None) -> dict:
    from agents.llm import ask_json, forget, model_name
    prompt = build_prompt(system, previous_code, feedback)
    result = ask_json(prompt, system=SYSTEM_PROMPT, label=f"generate:{system}")
    code = result.get("code", "")
    if code.startswith("```"):
        code = code.strip("`").removeprefix("python").strip()
    return {"code": code, "notes": result.get("notes", ""), "model": model_name(),
            "forget": lambda: forget(prompt, SYSTEM_PROMPT)}  # called if this code fails validation
