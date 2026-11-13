# 3-minute demo script

**Before recording:** run the full pipeline once so every page has data, then
`python scripts/simulate_drift.py --reset`. Have the dashboard open on Overview.
Terminal 1: portal API running. Close notifications.

| Time | Screen | Say |
|---|---|---|
| 0:00-0:20 | Overview page | "In a relay race, the baton never touches the ground. In hospitals, patient data gets dropped between systems every day: each integration takes weeks by hand. MedRelay's AI agents carry it into FHIR in minutes, with a human approving every step." |
| 0:20-0:45 | 1 · Discover, legacy DB | "Here's a 20-year-old database: `PT_DOB_DT`, sex codes 1/2/9. The Discover agent worked out what every field means, flagged the patient data, and it never saw a real value: everything is masked before the AI sees it." |
| 0:45-1:15 | 2 · Map review | "The Map agent matches each field to FHIR. Plain ML gets [Y]%; with Gemini re-ranking we get [X]%, and anything under 80% confidence comes here for a human." (Edit one row live.) |
| 1:15-1:50 | 3 · Build & validate | "The Generate agent writes the integration code. The Validate agent runs it on every record: security, FHIR structure, data fidelity. When it failed here, the errors went back and it fixed itself on attempt [N]." (Open the feedback expander.) |
| 1:50-2:15 | Patient 360 | "One patient, three systems, one FHIR record: demographics from the EHR, portal ID, lab results, all linked automatically." |
| 2:15-2:45 | Drift monitor | Click **Simulate schema change** → **Run drift monitor**. "A vendor upgrade renamed a column. The live integration broke for 200 patients. The agent found the rename, patched the code, re-validated, and is waiting for approval." Click **Approve fix**. |
| 2:45-3:00 | Overview | "[N] systems integrated in [T] minutes versus [H] hours by hand, [F]% data fidelity, zero real patient data exposed. MedRelay: the baton never drops." |

Fill in the [brackets] from your own run. Practise once with a timer.
