"""Streamlit UI: upload -> classify -> extract -> engineer verifies -> validate -> RAG compliance -> report."""
import os
import time

import pandas as pd
import streamlit as st

from src import config, pipeline, preprocess
from src.report import markdown_to_pdf
from src.schemas import DrawingType, Extraction, ParamStatus

os.makedirs(config.REPORTS_DIR, exist_ok=True)
os.makedirs(config.UPLOADS_DIR, exist_ok=True)

SUPPORTED = [t for t in DrawingType if t != DrawingType.UNKNOWN]
STATUS_VALUES = [s.value for s in ParamStatus]


@st.cache_resource(show_spinner="Loading knowledge base and embedding model...")
def get_retriever():
    from src.rag.retriever import Retriever

    return Retriever()


def reset_from(stage: str):
    """Drop everything computed after `stage` so stale results are never shown."""
    order = ["images", "urls", "classification", "chosen_type", "extraction", "validation", "results", "report_md"]
    for key in order[order.index(stage) + 1:]:
        st.session_state.pop(key, None)


def extraction_to_df(ex: Extraction) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "key": p.key,
            "Parameter": p.label,
            "Value": p.value or "",
            "Unit": p.unit or "",
            "Status": p.status.value,
            "Source on drawing": p.source_location or "",
            "Clarification needed": p.clarification or "",
            "Note": p.note or "",
        } for p in ex.params]
    )


def df_to_extraction(df: pd.DataFrame, original: Extraction) -> Extraction:
    before = original.as_dict()
    params = []
    for row in df.to_dict("records"):
        old = before[row["key"]]
        value = str(row["Value"]).strip() or None
        status = ParamStatus(row["Status"])
        if value and status == ParamStatus.MISSING:
            status = ParamStatus.FOUND  # engineer supplied the value
        if not value:
            status = ParamStatus.MISSING
        edited = old.edited or value != old.value or status != old.status
        params.append(old.model_copy(update={
            "value": value,
            "unit": str(row["Unit"]).strip() or None,
            "status": status,
            "edited": edited,
            "clarification": old.clarification if status != ParamStatus.FOUND else None,
        }))
    return original.model_copy(update={"params": params})


# ----------------------------------------------------------------------------- page
st.set_page_config(page_title="RCC Drawing Compliance Checker", page_icon="🧑‍🔬", layout="wide")
st.title("🧑‍🔬 RCC Drawing Compliance Checker")
st.caption("Foundation, column, slab and beam drawings against IS 456:2000 and SP 34:1987 - multi-agent RAG pipeline")

# --- Step 1: upload --------------------------------------------------------------
st.header("1. Upload drawing")
files = st.file_uploader(
    "PDF or image(s) of one drawing",
    type=["pdf", "png", "jpg", "jpeg", "webp", "bmp"],
    accept_multiple_files=True,
)
if files:
    names = tuple(f.name for f in files)
    if st.session_state.get("file_names") != names:
        reset_from("images")
        try:
            st.session_state.images = preprocess.load_inputs((f.name, f.getvalue()) for f in files)
            st.session_state.file_names = names
            for f in files:
                with open(config.UPLOADS_DIR / f.name, "wb") as out:
                    out.write(f.getbuffer())
        except Exception as e:
            st.error(f"Could not read the upload: {e}")
    images = st.session_state.get("images", [])
    if images:
        cols = st.columns(min(4, len(images)))
        for i, img in enumerate(images):
            cols[i % len(cols)].image(img, caption=f"Page {i + 1} ({img.width}x{img.height})", use_container_width=True)

# --- Step 2: classify ------------------------------------------------------------
if st.session_state.get("images"):
    st.header("2. Drawing type (Orchestrator)")
    if st.button("Classify drawing", type="primary", disabled="classification" in st.session_state):
        with st.spinner("Orchestrator classifying..."):
            try:
                st.session_state.urls = pipeline.image_urls(st.session_state.images)
                st.session_state.classification = pipeline.classify(st.session_state.urls)
            except Exception as e:
                st.error(f"Classification failed: {e}")

    cls = st.session_state.get("classification")
    if cls:
        st.write(f"Detected: **{cls.drawing_type.value}** - confidence {cls.confidence:.0%}. {cls.reason}")
        if cls.drawing_type == DrawingType.UNKNOWN:
            st.warning("Drawing not recognised as foundation / column / slab / beam. Pick a type to continue anyway.")
        default = SUPPORTED.index(cls.drawing_type) if cls.drawing_type in SUPPORTED else 0
        chosen = st.selectbox("Drawing type (override if wrong)", SUPPORTED, index=default, format_func=lambda t: t.value.title())
        if st.session_state.get("chosen_type") != chosen:
            reset_from("classification")
            st.session_state.chosen_type = chosen

# --- Step 3: extract + human verification ----------------------------------------
if st.session_state.get("chosen_type"):
    dtype = st.session_state.chosen_type
    st.header(f"3. Extracted parameters (Specialist - {dtype.value})")
    if "extraction" not in st.session_state:
        if st.button("Extract parameters", type="primary"):
            with st.spinner("Specialist reading the drawing..."):
                try:
                    st.session_state.extraction = pipeline.extract(st.session_state.urls, dtype)
                except Exception as e:
                    st.error(f"Extraction failed: {e}")

    ex = st.session_state.get("extraction")
    if ex:
        open_items = [p for p in ex.params if p.status != ParamStatus.FOUND]
        found = len(ex.params) - len(open_items)
        st.write(f"{found}/{len(ex.params)} parameters found. Review every value; fill or correct anything missing or ambiguous.")
        if open_items:
            with st.expander(f"❓ {len(open_items)} clarification(s) needed", expanded=True):
                for p in open_items:
                    st.markdown(f"- **{p.label}** ({p.status.value}): {p.clarification or ''}")

        edited_df = st.data_editor(
            extraction_to_df(ex),
            key=f"editor_{dtype.value}_{st.session_state.get('editor_version', 0)}",
            hide_index=True,
            use_container_width=True,
            disabled=["key", "Parameter", "Source on drawing", "Clarification needed", "Note"],
            column_config={
                "key": None,
                "Status": st.column_config.SelectboxColumn(options=STATUS_VALUES, required=True),
                "Value": st.column_config.TextColumn(width="medium"),
            },
        )
        if st.button("✅ Confirm values and validate", type="primary"):
            verified = df_to_extraction(edited_df, ex)
            st.session_state.extraction = verified
            st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1  # fresh editor on new data
            reset_from("extraction")
            with st.spinner("Validator checking consistency..."):
                st.session_state.validation = pipeline.validate(verified)
            st.rerun()

# --- Step 4: validation ----------------------------------------------------------
val = st.session_state.get("validation")
if val:
    st.header("4. Consistency check (Validator)")
    if not val.issues:
        st.success("No consistency issues found.")
    else:
        icon = {"error": "🔴", "warning": "🟠", "info": "🔵"}
        st.dataframe(
            pd.DataFrame([{"": icon.get(i.severity, ""), "Severity": i.severity, "Parameters": ", ".join(i.params),
                           "Finding": i.message, "By": i.source} for i in val.issues]),
            hide_index=True, use_container_width=True,
        )
        if val.has_errors:
            st.warning("Errors found. Fix the values in step 3 and confirm again, or continue if you have checked them.")
    if val.derived:
        with st.expander("Derived values"):
            st.json(val.derived)

    # --- Step 5: compliance --------------------------------------------------------
    st.header("5. Code compliance (RAG Compliance agent)")
    notes = st.text_area("Engineer notes (optional)", placeholder="e.g. site in Mangalore - take exposure as severe",
                         height=80)
    if st.button("🚀 Run compliance check", type="primary"):
        with st.spinner("Retrieving IS 456 / SP 34 clauses per check and evaluating..."):
            try:
                retriever = get_retriever()
                if retriever.collection.count() == 0:
                    st.error("Knowledge base is empty. Run `python -m src.rag.ingest` first.")
                else:
                    results = pipeline.comply(st.session_state.extraction, val, retriever, user_notes=notes)
                    st.session_state.results = results
                    st.session_state.report_md = pipeline.build_report(
                        st.session_state.extraction, val, results, st.session_state.get("classification"),
                        overridden=st.session_state.classification.drawing_type != st.session_state.chosen_type,
                        source_name=", ".join(st.session_state.get("file_names", ())),
                    )
            except Exception as e:
                st.error(f"Compliance check failed: {e}")

# --- Step 6: report --------------------------------------------------------------
if st.session_state.get("report_md"):
    st.header("6. Report")
    md = st.session_state.report_md
    st.markdown(md)
    stamp = int(time.time())
    c1, c2 = st.columns(2)
    c1.download_button("📥 Download Markdown", md, file_name=f"compliance_report_{stamp}.md", mime="text/markdown")
    pdf_path = config.REPORTS_DIR / f"compliance_report_{stamp}.pdf"
    ok, err = markdown_to_pdf(md, str(pdf_path))
    if ok and pdf_path.exists():
        c2.download_button("📄 Download PDF", pdf_path.read_bytes(), file_name=pdf_path.name, mime="application/pdf")
    else:
        c2.info(err or "PDF export unavailable.")

with st.sidebar:
    st.header("Pipeline")
    st.markdown(
        """
1. **Orchestrator** - classifies the drawing (temperature 0)
2. **Specialist** - extracts the type-specific schema, flags missing/ambiguous values
3. **Engineer** - verifies and corrects values
4. **Validator** - rule + LLM consistency checks
5. **RAG Compliance** - per-check retrieval from IS 456 / SP 34, cited verdicts
"""
    )
    for key, label in [("classification", "Classified"), ("extraction", "Extracted"), ("validation", "Validated"), ("results", "Checked")]:
        if key in st.session_state:
            st.success(label)
    if st.button("Start over"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
