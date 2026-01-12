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
        job_copy = job.copy()
        job_copy["score"] = round(sim * 100, 2)
        scored.append(job_copy)

    scored.sort(key=lambda j: j["score"], reverse=True)
    return scored


st.title("NI Job Matcher (Super Simple Version)")
st.write("Upload your CV or paste text. Shows NI jobs from Adzuna + Civil Service NI (RSS).")

option = st.radio("CV Input Method", ["Upload PDF", "Paste Text"])

cv_text = ""
file_bytes = None

if option == "Upload PDF":
    uploaded = st.file_uploader("Upload your CV (PDF)", type=["pdf"])
    if uploaded:
        file_bytes = uploaded.read()
else:
    cv_text = st.text_area("Paste your CV text here", height=300)

if st.button("Find Jobs"):
    if not file_bytes and not cv_text.strip():
        st.error("Please upload or paste your CV.")
    else:
        if file_bytes:
            cv_raw = extract_text_from_pdf(file_bytes)
        else:
            cv_raw = cv_text

        cv_clean = clean_text(cv_raw)

        with st.spinner("Fetching jobs..."):
            jobs = get_all_jobs()

        if not jobs:
            st.warning("No jobs found or sources unavailable.")
        else:
            scored = compute_scores(cv_clean, jobs)
            st.subheader("Job Matches")

            for job in scored:
                with st.container():
                    st.markdown(f"### {job['title']} ({job['company']})")
                    st.write(f"**Location:** {job['location']}")
                    st.write(f"**Source:** {job['source']}")
                    st.write(f"**Match Score:** {job['score']}%")
                    st.write(f"[Job Link]({job['url']})")
                    st.write("---")
