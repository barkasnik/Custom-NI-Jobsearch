# app.py

import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from PyPDF2 import PdfReader
import io
from job_source import get_all_jobs


def extract_text_from_pdf(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    text = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            text.append(t)
    return "\n".join(text)


def clean_text(text):
    return " ".join(text.lower().split())


def compute_scores(cv_text, jobs):
    """
    Compute similarity scores and adjust them so the percentages feel human:
    - Weak matches: ~20–40%
    - Medium matches: ~50–70%
    - Strong matches: ~75–95%
    """
    if not jobs:
        return []

    documents = [cv_text] + [job["description"].lower() for job in jobs]
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf = vectorizer.fit_transform(documents)

    cv_vec = tfidf[0:1]
    job_vecs = tfidf[1:]
    sims = cosine_similarity(cv_vec, job_vecs)[0]

    scored = []
    for job, sim in zip(jobs, sims):
        raw = sim * 100.0  # base similarity %
        # Adjust: soften low scores, boost mid-range a bit
        adjusted = (raw ** 0.75) * 1.5
        final = round(min(adjusted, 100.0), 2)

        job_copy = job.copy()
        job_copy["score"] = final
        scored.append(job_copy)

    scored.sort(key=lambda j: j["score"], reverse=True)
    return scored


st.title("NI Job Matcher (Super Simple, No API Keys)")
st.write(
    "Upload your CV or paste text. "
    "Shows jobs in Northern Ireland from Indeed (via RSS) and UK-wide Civil Service (NI roles only)."
)

option = st.radio("CV Input Method", ["Upload PDF", "Paste Text"])

cv_text = ""
file_bytes = None

if option == "Upload PDF":
    uploaded = st.file_uploader("Upload your CV (PDF)", type=["pdf"])
    if uploaded:
        file_bytes = uploaded.read()
else:
    cv_text = st.text_area("Paste your CV text here", height=300)

min_score = st.slider(
    "Minimum match score to show",
    min_value=0,
    max_value=100,
    value=40,
    step=5,
    help="Jobs below this score will be hidden.",
)

if st.button("Find Jobs"):
    if not file_bytes and not cv_text.strip():
        st.error("Please upload or paste your CV.")
    else:
        if file_bytes:
            cv_raw = extract_text_from_pdf(file_bytes)
        else:
            cv_raw = cv_text

        cv_clean = clean_text(cv_raw)

        with st.spinner("Fetching jobs from Indeed and Civil Service..."):
            jobs = get_all_jobs()

        if not jobs:
            st.warning("No jobs found or sources unavailable.")
        else:
            scored = compute_scores(cv_clean, jobs)
            filtered = [job for job in scored if job["score"] >= min_score]

            st.subheader(f"Job Matches (showing {len(filtered)} of {len(scored)} total)")

            if not filtered:
                st.info("No jobs meet the minimum match score. Try lowering the threshold.")
            else:
                for job in filtered:
                    with st.container():
                        st.markdown(f"### {job['title']} ({job['company']})")
                        st.write(f"**Location:** {job['location'] or 'Northern Ireland'}")
                        st.write(f"**Source:** {job['source']}")
                        st.write(f"**Match Score:** {job['score']}%")
                        st.write(f"[Job Link]({job['url']})")
                        st.write("---")
