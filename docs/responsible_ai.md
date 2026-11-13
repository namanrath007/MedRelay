# MedRelay - Responsible AI note

*Draft - edit with your own numbers from `outputs/` before submitting.*

## 1. Data
- **Synthetic only.** 200 generated patients; no real patient data was used at any stage.
- In a real deployment the same pipeline runs inside the client's tenant (e.g. Azure OpenAI), so PHI never
  leaves their environment. The LLM provider is one setting in `.env`.

## 2. Privacy by design (PHI minimisation)
- Agents see **schemas and at most 3 sample values per field**, never full records.
- Every sample is **masked before any LLM call** (`agents/privacy.py`): names → `S***`, dates → `########`,
  phones → `+##########79`, IDs → `40##01`. Format is kept so the model can still reason; content is hidden.
  Masking counts are logged (`outputs/discovery/privacy.json`): **[N] values masked** in our run.
- Validation feedback sent back to the LLM is masked the same way.
- The Discover agent flags every PHI field; the dashboard shows them for review.

## 3. Safe generated code
- Adapters are **pure functions**: connectors do the I/O, adapters only transform.
- An AST security scan rejects any adapter that imports `os`/`requests`/etc., calls `print`, logging,
  `open`, `eval`/`exec`, or contains a hard-coded secret. A rejected adapter is never executed.

## 4. Human in the loop - four gates
1. **Discovery** profiles are approved by a human.
2. **Mappings** below 0.80 confidence must be reviewed; any mapping can be edited (edits are counted).
3. **Generated adapters** must pass all checks; a human approves deployment.
4. **Drift fixes** are proposed with a code diff; nothing goes live without approval.

## 5. Validation & accuracy
- Mapping accuracy measured against an answer key: **[X]%** (ML baseline **[Y]%**), auto-approved precision **[Z]%**.
- Every record is converted and checked for FHIR structure and **data fidelity** against known-good data:
  **[F]%** of field values reproduced exactly.
- Every attempt, the feedback the agent received, and every code version are stored for audit.

## 6. Known limitations (be upfront with the judges)
- **Small benchmark**: 53 mapped fields across 3 systems we designed. Hard mode (no schema comments) tests robustness.
- **Fidelity needs golden data.** We compare against the synthetic truth; in production this would be a
  clinician-verified sample of records.
- **Lightweight FHIR validator**: our checker covers the R4 rules for the 4 resource types we produce; production
  would add the official HL7 validator (HAPI) and terminology checks.
- **Information lost at source**: the legacy EHR stores names in UPPERCASE, so `MCCARTHY` cannot be restored to
  `McCarthy` with certainty; we compare names case-insensitively and flag this as a data-quality finding.
- **LLM variability**: outputs can differ between runs; the confidence gate, validation loop and human approval
  contain this, but do not eliminate it.
- **Gender codes**: source systems only support male/female/unknown; FHIR also allows `other`. Mapping
  preserves what the source holds and does not infer.

## 7. Security
- API keys live in `.env` (git-ignored); the portal and FHIR API both require an API key header.
- No secrets in code - enforced by the security scan.
