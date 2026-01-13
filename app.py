import streamlit as st
from job_source import extract_text_from_upload, fetch_all_jobs, score_jobs

st.set_page_config(page_title="NI UK Civil Service Job Matcher", layout="wide")

BUILD = "2026-01-13 v6 (RSS-only, no NIJobs scraping, multi-profile scoring)"
st.title("NI UK Civil Service Job Matcher")
st.caption(f"BUILD: {BUILD}")

with st.sidebar:
    st.subheader("Your CV")
    uploaded = st.file_uploader("Upload CV (PDF/DOCX/TXT)", type=["pdf", "docx", "txt"])
    pasted = st.text_area("…or paste CV text", height=220, placeholder="Paste CV text here…")

    st.divider()
    st.subheader("Sources (RSS, key-free)")
    use_careerjet = st.checkbox("Careerjet RSS (NI baseline)", value=True)
    use_indeed = st.checkbox("Indeed RSS (often flaky)", value=True)

    st.divider()
    st.subheader("Filter")
    strict_gov_only = st.checkbox("Prefer government / civil service-ish jobs", value=True)
    extra_keywords = st.text_input("Optional keywords", placeholder="e.g. supervisor, operations, customer service, python")

    st.divider()
    st.subheader("Results")
    min_score = st.slider("Minimum match score", 40, 95, 50, 1)
    max_results = st.slider("Max results to show", 10, 100, 40, 5)
    show_diagnostics = st.toggle("Show diagnostics", value=True)

    st.divider()
    if st.button("Clear cache"):
        st.cache_data.clear()
        st.success("Cache cleared.")

# CV text (paste overrides upload)
cv_text = ""
if uploaded is not None:
    cv_text = extract_text_from_upload(uploaded)
if pasted.strip():
    cv_text = pasted.strip()

run = st.button("Find matches", type="primary", use_container_width=True)

if "searched" not in st.session_state:
    st.session_state.searched = False
if "results" not in st.session_state:
    st.session_state.results = []
if "diag" not in st.session_state:
    st.session_state.diag = {}

if run:
    st.session_state.searched = True

    with st.spinner("Fetching jobs (RSS)…"):
        jobs, diag = fetch_all_jobs(
            use_careerjet=use_careerjet,
            use_indeed=use_indeed,
            strict_gov_only=strict_gov_only,
            extra_keywords=extra_keywords.strip(),
        )
        st.session_state.diag = diag

    with st.spinner("Scoring matches…"):
        scored = score_jobs(cv_text, jobs)

    # Filter by score, but never show “nothing” if we fetched jobs
    filtered = [r for r in scored if r["score"] >= min_score]
    if not filtered and scored:
        filtered = scored[:20]
        st.info("Nothing met your minimum score, so I’m showing the closest matches instead.")

    st.session_state.results = filtered[:max_results]

st.divider()
st.subheader("Results")

if not st.session_state.searched:
    st.info("Paste/upload your CV (optional), then click **Find matches**.")
else:
    counts = (st.session_state.diag.get("counts") or {})
    fetched_total = counts.get("Deduped total", 0)

    if fetched_total == 0:
        st.error("0 jobs fetched from RSS feeds. Open Diagnostics below to see which feed failed.")
    elif not st.session_state.results:
        st.warning("Jobs were fetched, but none survived filters/scoring. Lower the minimum score.")
    else:
        st.write(f"Showing **{len(st.session_state.results)}** matches (from **{fetched_total}** fetched).")

        for r in st.session_state.results:
            with st.container(border=True):
                cols = st.columns([4, 1])
                with cols[0]:
                    st.markdown(f"### [{r['title']}]({r['url']})")
                    meta = []
                    if r.get("company"):
                        meta.append(r["company"])
                    if r.get("location"):
                        meta.append(r["location"])
                    meta.append(f"Source: {r.get('source','')}")
                    if r.get("profile"):
                        meta.append(f"Matched via: {r['profile']}")
                    st.write(" • ".join([m for m in meta if m]))

                    if r.get("summary"):
                        st.write(r["summary"])

                    if r.get("why"):
                        st.caption("Matched terms: " + ", ".join(r["why"][:12]))

                with cols[1]:
                    st.metric("Match", f"{r['score']}%")
                    st.progress(r["score"] / 100)

if show_diagnostics and st.session_state.searched:
    st.divider()
    st.subheader("Diagnostics")

    st.write("**Counts**")
    st.json(st.session_state.diag.get("counts", {}))

    if st.session_state.diag.get("feeds"):
        st.write("**Feed checks** (status / entries)")
        st.json(st.session_state.diag["feeds"])

    if st.session_state.diag.get("errors"):
        st.write("**Errors**")
        for e in st.session_state.diag["errors"]:
            st.code(e)

    st.caption(
        "If you still see NIJobs timeouts here, you are not running this build. "
        "In Streamlit Cloud settings, make sure the main file is app.py, then Reboot."
    )
