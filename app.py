"""
app.py — Optional Streamlit UI for the AI Compliance Validator
Run with:  streamlit run app.py
"""

import tempfile
import json
from pathlib import Path

import streamlit as st

from validator.ingestion import load_document, load_rules, chunk_text
from validator.vector_store import build_store
from validator.agent import run_validation, MODEL
from validator.reporter import generate_report
import validator.agent as ag

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Compliance Validator",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 AI Compliance Validator")
st.caption("AMD Hackathon | vLLM + ChromaDB RAG | Powered by LLM-as-Judge")

# ── Sidebar — config ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")
    model_name = st.text_input("vLLM Model Name", value=MODEL)
    vllm_url   = st.text_input("vLLM Base URL", value="http://localhost:8000/v1")
    top_k      = st.slider("Chunks retrieved per rule (top-k)", 1, 6, 3)
    chunk_size = st.slider("Chunk size (tokens)", 200, 1000, 500, step=50)

    if st.button("Apply Settings"):
        ag.MODEL = model_name
        from openai import OpenAI
        ag.client = OpenAI(base_url=vllm_url, api_key="dummy")
        st.success("Settings applied!")

# ── File uploaders ────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    doc_file = st.file_uploader("📄 Upload Document (PDF or TXT)", type=["pdf", "txt"])

with col2:
    rules_file = st.file_uploader("📋 Upload Rules File (TXT)", type=["txt"])

# ── Run validation ────────────────────────────────────────────────────────────
if st.button("🚀 Run Validation", type="primary", disabled=not (doc_file and rules_file)):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write uploaded files to temp paths
        doc_ext  = Path(doc_file.name).suffix
        doc_path = str(Path(tmpdir) / f"document{doc_ext}")
        with open(doc_path, "wb") as f:
            f.write(doc_file.read())

        rules_path = str(Path(tmpdir) / "rules.txt")
        with open(rules_path, "w", encoding="utf-8") as f:
            f.write(rules_file.read().decode("utf-8"))

        with st.spinner("Chunking document & building vector store..."):
            doc_text = load_document(doc_path)
            chunks   = chunk_text(doc_text, chunk_size=chunk_size)
            col_     = build_store(chunks)

        with st.spinner("Loading rules..."):
            rules = load_rules(rules_path)

        progress_bar = st.progress(0, text="Validating rules...")
        results = []
        for i, rule in enumerate(rules):
            from validator.agent import validate_rule
            r = validate_rule(rule, col_, top_k=top_k)
            results.append(r)
            progress_bar.progress((i + 1) / len(rules), text=f"Checked {rule['id']}")

        report = generate_report(results, doc_name=doc_file.name)
        progress_bar.empty()

    # ── Summary metrics ───────────────────────────────────────────────────────
    s = report["summary"]
    st.subheader("📊 Summary")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Compliance Score", f"{s['compliance_score']:.1f}%")
    m2.metric("Total Rules",      s["total_rules"])
    m3.metric("✅ Passed",         s["passed"])
    m4.metric("❌ Failed",         s["failed"])
    m5.metric("❓ Unclear",        s["unclear"])

    # ── Findings table ────────────────────────────────────────────────────────
    st.subheader("📋 Findings")
    for f in report["findings"]:
        v      = f["verdict"]
        icon   = {"PASS": "✅", "FAIL": "❌", "UNCLEAR": "❓"}.get(v, "")
        color  = {"PASS": "🟢", "FAIL": "🔴", "UNCLEAR": "🟡"}.get(v, "")
        label  = f"{color} {f['rule_id']} — {f['rule_text'][:70]}"

        with st.expander(f"{icon} {label}  (conf: {f['confidence']:.2f})"):
            st.write(f"**Verdict:** {v}")
            st.write(f"**Confidence:** {f['confidence']:.2f}")
            st.write(f"**Evidence:** {f.get('evidence', 'N/A')}")
            st.write(f"**Explanation:** {f.get('explanation', 'N/A')}")

    # ── Download report ───────────────────────────────────────────────────────
    st.download_button(
        label="⬇️  Download JSON Report",
        data=json.dumps(report, indent=2),
        file_name="audit_report.json",
        mime="application/json",
    )
