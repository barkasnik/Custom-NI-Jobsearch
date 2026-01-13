import streamlit as st
from job_source import (
    extract_text_from_upload,
    fetch_all_jobs,
    score_jobs,
)

st.set_page_config(page_title="NI Job Matcher (UK Civil Service)", layout="wide")

st.title("NI Job Matcher (UK Civil Service roles)")
st.caption(
    "Matches your CV to UK Civil Service-style roles located in Northern Ireland. "
    "No API keys. Runs on Streamlit Cloud."
)

with st.sidebar:
    st.subheader("Your CV")
    uploaded = st.file_uploader(
        "Upload CV (PDF, DOCX, TXT)",
        type=["pdf", "docx", "txt"],
        help="Uploading is optional — you can paste text instead.",
    )
    pasted = st.text_area(
        "…or paste CV text",
        height=220,
        placeholder="Paste your CV / personal statement here…",
    )

    st.divider()
    st.subheader("Filters")
    min_score = st.slider("Minimum match score", 40, 95, 60, 1)
    max_results = st.slider("Max results to show", 10, 100, 40, 5)
    show_diagnostics = st.toggle("Show diagnostics", value=False)

# Resolve CV text
cv_text = ""
if uploaded is not None:
    cv_text = extract_text_from_upload(uploaded)
elif pasted.strip():
    cv_text = pasted.strip()

# Button (main area, obvious)
colA, colB = st.columns([1, 3])
with colA:
    run = st.button("Find matches", type="primary", use_container_width=True)
with colB:
    st.write("Tip: you can run it even without a CV — you’ll still get jobs, just less meaningful scoring.")

# Session state flags
if "searched" not in st.session_state:
    st.session_state["searched"] = False
if "results" not in st.session_state:
    st.session_state["results"] = []
if "diag" not in st.session_state:
    st.session_state["diag"] = {}

if run:
    st.session_state["searched"] = True
    with st.spinner("Fetching jobs…"):
        jobs, diag = fetch_all_jobs()
    st.session_state["diag"] = diag

    with st.spinner("Scoring matches…"):
        results = score_jobs(cv_text, jobs)

    # Apply UI filters
    results = [r for r in results if r["score"] >= min_score]
    results = results[:max_results]

    st.session_state["results"] = results

# --- Render state-aware output ---
results = st.session_state["results"]

if not st.session_state["searched"]:
    st.info("Upload/paste your CV (optional), then click **Find matches**.")
else:
    # Search has run
    if not results:
        st.warning(
            "Search ran, but **0 results** passed your filters. "
            "Try lowering **Minimum match score** in the sidebar."
        )
    else:
        st.subheader(f"Matches ({len(results)})")

        for r in results:
            left, right = st.columns([3, 1])

            with left:
                st.markdown(f"### [{r['title']}]({r['url']})")
                meta = []
                if r.get("company"):
                    meta.append(r["company"])
                if r.get("location"):
                    meta.append(r["location"])
                if r.get("source"):
                    meta.append(f"Source: {r['source']}")
                st.write(" • ".join(meta) if meta else "")

                if r.get("summary"):
                    st.write(r["summary"])

                if r.get("why"):
                    st.caption("Matched on: " + ", ".join(r["why"][:10]))

            with right:
                st.metric("Match", f"{r['score']}%")
                st.progress(r["score"] / 100)

            st.divider()

# --- Diagnostics ---
if show_diagnostics and st.session_state["searched"]:
    st.subheader("Diagnostics")
    diag = st.session_state.get("diag", {}) or {}

    st.write("**Counts**")
    st.json(diag.get("counts", {}))

    if diag.get("errors"):
        st.write("**Errors**")
        for e in diag["errors"]:
            st.code(e)

    st.write("**Notes**")
    st.write(
        "- If a source shows 0, it may be temporarily blocking server requests.\n"
        "- NIJobs is the primary source and should usually return items. "
        "It lists 'Civil Service' jobs in Northern Ireland. :contentReference[oaicite:1]{index=1}\n"
        "- The official Civil Service Jobs portal can be anti-bot protected, which is why apps often get 0 from it. "
        ":contentReference[oaicite:2]{index=2}"
    )
