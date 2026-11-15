"""
MedRelay dashboard - the human-in-the-loop control room.

Run (from the fhirbridge folder):
    python -m streamlit run dashboard/app.py

Pages: Overview | 1 Discover | 2 Map review | 3 Build & validate | Patient 360 | Drift monitor | Assistant
The mock portal API must be running on :8001 for pipeline buttons that read it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agents.fhir_catalog import CATALOG  # noqa: E402
from fhir_api.store import everything, load_store, stats  # noqa: E402

SYSTEMS = {"legacy_db": "Legacy EHR database", "rest_api": "Patient portal API", "hl7_feed": "Lab HL7 feed"}
OUT = ROOT / "outputs"

st.set_page_config(page_title="MedRelay", page_icon="🩺", layout="wide")


# ---------------------------------------------------------------- self-starting backend (for hosted demos)
# Streamlit Community Cloud only runs this file, so on first load we: copy hosted secrets into the
# environment, rebuild the synthetic data if it is missing, and start the two internal APIs.
@st.cache_resource(show_spinner="Starting MedRelay services (first load only)...")
def ensure_backend():
    import time
    import urllib.request
    try:  # hosted secrets (Streamlit Cloud) -> environment, so agents/subprocesses see them
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float, bool)):
                os.environ.setdefault(k, str(v))
    except Exception:
        pass
    status = {}
    if not (ROOT / "mock_systems" / "legacy_db" / "legacy_ehr.db").exists() or \
            not any((ROOT / "mock_systems" / "hl7_feed" / "outbox").glob("*.hl7")):
        r = subprocess.run([sys.executable, "scripts/build_all.py"], cwd=ROOT, capture_output=True, text=True)
        status["data"] = "built" if r.returncode == 0 else f"build failed: {r.stderr[-300:]}"

    def up(port, path):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1)
            return True
        except Exception:
            return False

    for port, app, path in ((8001, "mock_systems.rest_api.app:app", "/health"),
                            (8002, "fhir_api.app:app", "/fhir/metadata")):
        if not up(port, path):
            subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port)],
                             cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                if up(port, path):
                    break
                time.sleep(0.5)
        status[port] = "up" if up(port, path) else "not running"
    return status


if os.getenv("AUTO_START", "1") == "1":
    BACKEND = ensure_backend()


# ---------------------------------------------------------------- helpers
def load(rel):
    p = OUT / rel
    return json.loads(p.read_text()) if p.exists() else None


def save(rel, data):
    (OUT / rel).write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------- public demo mode
# DEMO_MODE=1 (set on the hosting platform): visitors can browse every result and run the drift demo,
# but anything that spends Gemini quota or changes shared results needs ADMIN_PASSWORD.
from fhirbridge_runtime import env  # noqa: E402,F401  (loads .env locally)

DEMO = os.getenv("DEMO_MODE", "0") == "1"
ASSISTANT_LIMIT = int(os.getenv("DEMO_ASSISTANT_LIMIT", "5"))


def is_admin() -> bool:
    return not DEMO or st.session_state.get("admin", False)


def locked(what: str = "This action") -> bool:
    """True (and shows a note) if a demo visitor tries an admin-only action."""
    if is_admin():
        return False
    st.warning(f"{what} is reserved for the team in the public demo (it changes shared results or uses "
               "Gemini quota). All results shown were produced by the real pipeline.")
    return True


def run(cmd: list[str], label: str, public: bool = False):
    if not public and locked(label):
        return
    with st.spinner(f"{label}..."):
        proc = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    (st.success if proc.returncode == 0 else st.error)(f"{label}: {'done' if proc.returncode == 0 else 'failed'}")
    st.code(out[-5000:] or "(no output)", language="text")


def badge(ok, yes="Done", no="Pending"):
    return f"✅ {yes}" if ok else f"⏳ {no}"


# ---------------------------------------------------------------- sidebar
st.sidebar.title("🩺 MedRelay")
st.sidebar.caption("AI agents that carry hospital data into FHIR - without dropping a thing")
page = st.sidebar.radio("Go to", ["Overview", "1 · Discover", "2 · Map review", "3 · Build & validate",
                                  "Patient 360", "Drift monitor", "Assistant"])
st.sidebar.divider()
if "BACKEND" in globals():
    ok = BACKEND.get(8001) == "up" and BACKEND.get(8002) == "up"
    st.sidebar.caption(("🟢" if ok else "🔴") + f" Services: portal API {BACKEND.get(8001)} · FHIR API {BACKEND.get(8002)}"
                       + (f" · data {BACKEND['data']}" if "data" in BACKEND else ""))
st.sidebar.caption("All data is synthetic. Agents only ever see privacy-masked samples.")
if DEMO:
    st.sidebar.info("Public demo: browse all results and try the Drift monitor. "
                    "Running the agents is reserved for the team.")
    if not st.session_state.get("admin"):
        pw = st.sidebar.text_input("Team password", type="password")
        if pw and pw == os.getenv("ADMIN_PASSWORD", "") and os.getenv("ADMIN_PASSWORD"):
            st.session_state.admin = True
            st.rerun()
        elif pw:
            st.sidebar.error("Wrong password")
    else:
        st.sidebar.success("Team mode: all actions enabled")

# ---------------------------------------------------------------- OVERVIEW
if page == "Overview":
    st.title("Integration overview")
    ev = (load("mapping/evaluation.json") or {}).get("summary", {})
    priv = load("discovery/privacy.json") or {}
    vals = {s: load(f"validation/{s}.json") for s in SYSTEMS}
    passed = sum(1 for v in vals.values() if v and v["passed"])
    store = load_store()
    st_stats = stats(store) if store else {}

    c = st.columns(5)
    c[0].metric("Systems integrated", f"{passed} / {len(SYSTEMS)}")
    c[1].metric("Mapping accuracy", f"{ev.get('fhirbridge_accuracy_pct', '-')}%",
                f"ML baseline {ev.get('ml_baseline_accuracy_pct', '-')}%", delta_color="off")
    fids = [v["attempts"][-1]["result"]["fidelity"]["fidelity_pct"] for v in vals.values()
            if v and v["attempts"][-1]["result"].get("fidelity")]
    c[2].metric("Data fidelity", f"{min(fids) if fids else '-'}%", "lowest system", delta_color="off")
    c[3].metric("FHIR resources", sum(v for k, v in st_stats.items() if k != "patients_in_3_systems") or "-")
    c[4].metric("PHI values masked", priv.get("total", "-"))

    rows = []
    for s, name in SYSTEMS.items():
        d, m, v = load(f"discovery/{s}.json"), load(f"mapping/{s}.json"), vals[s]
        rows.append({
            "System": name, "Discover": badge(d and d.get("analysis")),
            "Map": badge(m), "Needs review": sum(x["status"] == "needs_review" for x in m["mappings"]) if m else "-",
            "Build & validate": ("✅ Passed" if v and v["passed"] else "❌ Failed" if v else "⏳ Pending"),
            "Attempts": v["attempts_used"] if v else "-",
            "Agent time (s)": round(sum(filter(None, [
                sum(filter(None, (d or {}).get("timing_seconds", {}).values())),
                sum(filter(None, (m or {}).get("timing_seconds", {}).values())),
                (v or {}).get("total_seconds")])), 1),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    with st.expander("⏱ Where did the time go? (every Gemini call is timed)"):
        from scripts.llm_timing import summary as llm_summary
        timing = llm_summary()
        if timing:
            st.dataframe(pd.DataFrame(timing), hide_index=True, use_container_width=True)
            st.caption("Everything except the model calls takes well under a second. "
                       "'from_cache' = answered instantly because the same question was asked before.")
        else:
            st.caption("No model calls logged yet.")

    st.subheader("Time saved")
    st.caption("Enter the time your team measured for building ONE integration by hand.")
    manual_h = st.number_input("Manual build time per integration (hours)", min_value=0.0, value=0.0, step=0.5)
    agent_s = sum(r["Agent time (s)"] for r in rows)
    if manual_h > 0 and agent_s:
        manual_total = manual_h * len(SYSTEMS)
        st.success(f"Agents: **{agent_s / 60:.1f} min** for {len(SYSTEMS)} systems vs **{manual_total:.1f} h** by hand "
                   f"→ about **{manual_total * 3600 / agent_s:.0f}× faster** (before human review time).")

    st.subheader("Run the pipeline")
    if st.button("▶ Run full pipeline (discover → map → evaluate → build & validate)"):
        run(["run_pipeline.py"], "Pipeline")

# ---------------------------------------------------------------- DISCOVER
elif page == "1 · Discover":
    st.title("1 · Discover")
    if st.button("▶ Run Discover agent on all systems"):
        run(["-m", "agents.discover"], "Discover")
    s = st.selectbox("System", list(SYSTEMS), format_func=SYSTEMS.get)
    d = load(f"discovery/{s}.json")
    if not d:
        st.info("Not discovered yet.")
    else:
        a = d.get("analysis") or {}
        st.write(a.get("system_summary", ""))
        c = st.columns(3)
        c[0].metric("Fields", len(d["profile"]["fields"]))
        c[1].metric("PHI fields", sum(1 for f in a.get("fields", []) if f.get("is_phi")))
        c[2].metric("Pattern", (a.get("integration_pattern") or {}).get("pattern", "-"))
        st.markdown(f"**Patient identifier:** `{(a.get('patient_identifier') or {}).get('field')}` · "
                    f"**Link keys:** " + ", ".join(f"`{k.get('field')}`" for k in a.get("link_keys", [])))
        if a.get("fields"):
            st.dataframe(pd.DataFrame(a["fields"]), hide_index=True, use_container_width=True)
        with st.expander("Risks & data-quality notes"):
            for r in a.get("risks", []) + a.get("data_quality_notes", []):
                st.write("•", r)
        st.caption(f"Status: **{d['status']}**")
        if d["status"] != "approved" and st.button("✅ Approve discovery profile") and not locked("Approving"):
            d["status"] = "approved"
            save(f"discovery/{s}.json", d)
            st.rerun()

# ---------------------------------------------------------------- MAP REVIEW
elif page == "2 · Map review":
    st.title("2 · Map review")
    c = st.columns(2)
    if c[0].button("▶ Run Map agent"):
        run(["-m", "agents.map"], "Map")
    if c[1].button("📊 Evaluate vs answer key"):
        run(["scripts/evaluate_mapping.py"], "Evaluation")
    s = st.selectbox("System", list(SYSTEMS), format_func=SYSTEMS.get)
    m = load(f"mapping/{s}.json")
    if not m:
        st.info("Not mapped yet.")
    else:
        df = pd.DataFrame([{"source": x["source"], "target": x["target"] or "none", "transform": x["transform"],
                            "confidence": x["confidence"], "status": x["status"], "reason": x["reason"]}
                           for x in m["mappings"]])
        df = df.sort_values(["status", "confidence"], ascending=[False, True])
        st.caption(f"Confidence gate {m['threshold']}: below it, a human must approve. "
                   f"Edit the target if it's wrong, then save.")
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, key=f"ed_{s}",
            column_config={"target": st.column_config.SelectboxColumn("target", options=list(CATALOG)),
                           "confidence": st.column_config.ProgressColumn("confidence", min_value=0, max_value=1)},
            disabled=["source", "confidence", "status", "reason"])
        c = st.columns(2)
        if c[0].button("💾 Save my edits (marks edited rows approved)") and not locked("Saving edits"):
            by_src = {x["source"]: x for x in m["mappings"]}
            changed = 0
            for _, row in edited.iterrows():
                x = by_src[row["source"]]
                new_t = None if row["target"] == "none" else row["target"]
                if new_t != x["target"] or row["transform"] != x["transform"]:
                    x.update({"target": new_t, "transform": row["transform"], "status": "approved",
                              "decided_by": "human"})
                    changed += 1
            m["human_edits"] = m.get("human_edits", 0) + changed
            save(f"mapping/{s}.json", m)
            st.success(f"Saved {changed} human edit(s).")
            st.rerun()
        pending = [x for x in m["mappings"] if x["status"] == "needs_review"]
        if pending and c[1].button(f"✅ Approve all {len(pending)} pending as shown") and not locked("Approving"):
            for x in pending:
                x.update({"status": "approved", "decided_by": "human"})
            save(f"mapping/{s}.json", m)
            st.rerun()
    ev = load("mapping/evaluation.json")
    if ev:
        with st.expander("Evaluation vs answer key"):
            st.json(ev["summary"])

# ---------------------------------------------------------------- BUILD & VALIDATE
elif page == "3 · Build & validate":
    st.title("3 · Build & validate")
    st.caption("Generate agent writes the adapter → Validate agent runs security, FHIR and fidelity checks "
               "on every record → failures go back for another attempt (max 3).")
    s = st.selectbox("System", list(SYSTEMS), format_func=SYSTEMS.get)
    if st.button(f"▶ Generate + validate {SYSTEMS[s]}"):
        run(["-m", "agents.validate", "--only", s], "Build & validate")
    v = load(f"validation/{s}.json")
    if not v:
        st.info("Not built yet.")
    else:
        (st.success if v["passed"] else st.error)(
            f"{'PASSED' if v['passed'] else 'FAILED'} after {v['attempts_used']} attempt(s) in {v['total_seconds']}s")
        for att in v["attempts"]:
            r = att["result"]
            with st.expander(f"Attempt {att['attempt']}: {att['summary']}", expanded=att is v["attempts"][-1]):
                if att.get("feedback_sent"):
                    st.markdown("**Feedback the agent received before this attempt:**")
                    st.code(att["feedback_sent"], language="text")
                if r.get("security"):
                    st.error("Security: " + "; ".join(r["security"]))
                if r.get("structure_examples"):
                    st.warning("FHIR structure problems:")
                    st.json(r["structure_examples"])
                if r.get("fidelity"):
                    st.write(f"Fidelity: **{r['fidelity']['fidelity_pct']}%** "
                             f"({r['fidelity']['passed']}/{r['fidelity']['checks']} checks) · "
                             f"resources: {r.get('resources')}")
                st.code(att["code"], language="python")

# ---------------------------------------------------------------- PATIENT 360
elif page == "Patient 360":
    st.title("Patient 360 - one patient, three systems, one FHIR record")
    store = load_store()
    if not store.get("Patient"):
        st.info("Nothing published yet - run Build & validate first.")
    else:
        pts = store["Patient"]
        ranked = sorted(pts, key=lambda pid: -len(pts[pid].get("meta", {}).get("tag", [])))
        pid = st.selectbox("Patient (MRN)", ranked,
                           format_func=lambda i: f"{i} · " + " ".join(
                               [(pts[i].get('name') or [{}])[0].get('family', '')] +
                               (pts[i].get('name') or [{}])[0].get('given', [])))
        b = everything(store, pid)
        p = pts[pid]
        sources = [t["code"] for t in p.get("meta", {}).get("tag", [])]
        c = st.columns(4)
        name = (p.get("name") or [{}])[0]
        c[0].metric("Name", f"{' '.join(name.get('given', []))} {name.get('family', '')}")
        c[1].metric("Born", p.get("birthDate", "-"))
        c[2].metric("Gender", p.get("gender", "-"))
        c[3].metric("Source systems", len(sources))
        st.write("Contributing systems:", ", ".join(SYSTEMS.get(x, x) for x in sources))
        st.write("Identifiers:", ", ".join(f"`{i.get('value')}` ({i.get('system')})" for i in p.get("identifier", [])))
        res = [e["resource"] for e in b["entry"][1:]]
        enc = [{"id": r["id"], "class": (r.get("class") or {}).get("code"), "start": (r.get("period") or {}).get("start"),
                "end": (r.get("period") or {}).get("end"), "status": r.get("status")} for r in res if r["resourceType"] == "Encounter"]
        cond = [{"code": ((r.get("code") or {}).get("coding") or [{}])[0].get("code"),
                 "diagnosis": ((r.get("code") or {}).get("coding") or [{}])[0].get("display"),
                 "onset": r.get("onsetDateTime")} for r in res if r["resourceType"] == "Condition"]
        obs = [{"test": ((r.get("code") or {}).get("coding") or [{}])[0].get("display"),
                "value": (r.get("valueQuantity") or {}).get("value"), "unit": (r.get("valueQuantity") or {}).get("unit"),
                "flag": (((r.get("interpretation") or [{}])[0].get("coding") or [{}])[0]).get("code"),
                "when": r.get("effectiveDateTime")} for r in res if r["resourceType"] == "Observation"]
        for title, rows in (("Encounters (legacy EHR)", enc), ("Diagnoses (legacy EHR)", cond), ("Lab results (HL7 feed)", obs)):
            st.subheader(title)
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True) if rows else st.caption("none")
        with st.expander("Raw FHIR Bundle (Patient/$everything)"):
            st.json(b)

# ---------------------------------------------------------------- DRIFT
elif page == "Drift monitor":
    st.title("Drift monitor - self-healing integrations")
    st.caption("Simulate a vendor upgrade renaming a column; the agent detects the break, diagnoses it, "
               "patches the adapter, re-validates, and waits for your approval.")
    st.info("Demo order: **1** Simulate schema change → **2** Run drift monitor → **3** Approve fix → **4** Reset demo")
    c = st.columns(4)
    if c[0].button("1 · 💥 Simulate schema change"):
        run(["scripts/simulate_drift.py", "--apply"], "Simulate drift", public=True)
        st.caption("Now click **2 · Run drift monitor**.")
    if c[1].button("2 · 🔍 Run drift monitor"):
        run(["-m", "agents.drift"] + ([] if is_admin() else ["--no-llm"]), "Drift monitor", public=True)
    pending = (load("drift/latest.json") or {}).get("status") == "fix_pending_approval"  # read after step 2 ran
    if c[2].button("3 · ✅ Approve fix", disabled=not pending,
                   help=None if pending else "Nothing to approve yet - run steps 1 and 2 first"):
        run(["-m", "agents.drift", "--approve"], "Approve fix", public=True)
    if c[3].button("4 · ↺ Reset demo"):
        run(["scripts/simulate_drift.py", "--reset"], "Reset", public=True)
    d = load("drift/latest.json")
    if d:
        status = d.get("status")
        {"healthy": st.success, "fixed": st.success, "fix_pending_approval": st.warning}.get(status, st.error)(
            f"Status: **{status}** · checked {d.get('checked_at')} · {d.get('seconds_to_diagnose_and_fix')}s to diagnose + fix")
        st.write(f"Removed: `{d.get('removed')}` · Added: `{d.get('added')}`")
        st.write(f"Live adapter: {d.get('live_adapter')}")
        for p in d.get("diagnosis", []):
            st.info(f"**{p['old']} → {p['new']}** (rule score {p['rule_score']}"
                    + (f", LLM confirmed: {p.get('llm_confirmed')} - {p.get('reason')}" if "llm_confirmed" in p else "") + ")")
        if d.get("proposed_fix"):
            st.write(f"Proposed fix: {d['proposed_fix']}")
        if d.get("diff"):
            st.code(d["diff"], language="diff")

# ---------------------------------------------------------------- ASSISTANT
elif page == "Assistant":
    st.title("Integration assistant")
    st.caption("Ask about the systems, mappings, validation results or drift. "
               "It sees agent outputs only - never patient records.")

    def context() -> str:
        ctx = {"evaluation": (load("mapping/evaluation.json") or {}).get("summary"), "drift": None, "systems": {}}
        dr = load("drift/latest.json")
        if dr:
            ctx["drift"] = {k: dr.get(k) for k in ("status", "removed", "added", "diagnosis", "proposed_fix")}
        for s in SYSTEMS:
            d, m, v = load(f"discovery/{s}.json"), load(f"mapping/{s}.json"), load(f"validation/{s}.json")
            a = (d or {}).get("analysis") or {}
            ctx["systems"][s] = {
                "summary": a.get("system_summary"), "patient_identifier": a.get("patient_identifier"),
                "integration_pattern": a.get("integration_pattern"), "risks": a.get("risks"),
                "fields": [{k: f.get(k) for k in ("name", "meaning", "format", "is_phi")} for f in a.get("fields", [])],
                "mappings": [{k: x[k] for k in ("source", "target", "transform", "confidence", "status")}
                             for x in (m or {}).get("mappings", [])],
                "validation": {"passed": v["passed"], "attempts": [a_["summary"] for a_ in v["attempts"]],
                               "last_feedback": v["attempts"][-1].get("feedback_sent")} if v else None}
        return json.dumps(ctx, default=str)

    if "chat" not in st.session_state:
        st.session_state.chat = []
    for role, text in st.session_state.chat:
        st.chat_message(role).write(text)
    asked = sum(1 for r, _ in st.session_state.chat if r == "user")
    if not is_admin():
        st.caption(f"Public demo: {max(ASSISTANT_LIMIT - asked, 0)} of {ASSISTANT_LIMIT} questions left.")
    q = st.chat_input("e.g. Why did the lab feed need two attempts?  Which fields hold PHI?",
                      disabled=not is_admin() and asked >= ASSISTANT_LIMIT)
    if q:
        st.session_state.chat.append(("user", q))
        st.chat_message("user").write(q)
        from agents.llm import ask_json
        history = "\n".join(f"{r}: {t}" for r, t in st.session_state.chat[-6:])
        with st.spinner("Thinking..."):
            try:
                reply = ask_json(
                    f"You are the MedRelay integration assistant for a healthcare data-integration project. "
                    f"Answer questions about this project using the context below (agent outputs only, no patient "
                    f"records), and general healthcare-integration questions (FHIR, HL7, PHI) from your own "
                    f"knowledge. Be concise and specific; cite field names where relevant.\n\nCONTEXT:\n{context()}"
                    f"\n\nCONVERSATION:\n{history}\n\nReturn JSON: {{\"answer\": \"your answer in markdown\"}}")
                ans = (reply.get("answer") or reply.get("response") or reply.get("text")
                       or (json.dumps(reply, indent=1) if reply else "")) if isinstance(reply, dict) else str(reply)
                ans = ans or "I didn't get an answer back from the model - please try again."
            except Exception as e:
                text = str(e)
                if "quota" in text.lower() or "RESOURCE_EXHAUSTED" in text:
                    ans = ("⚠️ Gemini's free daily quota is used up, so I can't answer right now. "
                           "It resets daily - or put a teammate's API key in `.env` and restart the dashboard.")
                else:
                    ans = f"Sorry - the model call failed: {text[:300]}"
        st.session_state.chat.append(("assistant", ans))
        st.chat_message("assistant").write(ans)
