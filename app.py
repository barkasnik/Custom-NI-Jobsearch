import re
from urllib.parse import quote_plus
import streamlit as st
import requests
import feedparser

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


st.set_page_config(page_title="NI UK Civil Service Job Matcher", layout="wide")

HEADERS = {"User-Agent": "Mozilla/5.0 (Streamlit Job Matcher)"}

NI_PLACES = [
    "Belfast", "Lisburn", "Newry", "Derry", "Londonderry", "Antrim", "Armagh",
    "Omagh", "Enniskillen", "Coleraine", "Ballymena", "Craigavon", "Bangor",
    "Carrickfergus"
]

NICS_SIGNALS = [
    "Northern Ireland Civil Service", "NI Civil Service", "NICS",
    "irecruit-ext.hrconnect", "hrconnect.nigov", "IRC3"  # common NICS ref patterns
]

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def looks_like_ni(text: str) -> bool:
    t = (text or "").lower()
    return any(p.lower() in t for p in NI_PLACES) or "northern ireland" in t

def is_nics(text: str) -> bool:
    t = (text or "").lower()
    return any(sig.lower() in t for sig in NICS_SIGNALS)

def fetch_rss(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.text)

@st.cache_data(ttl=900)
def fetch_indeed_cs_jobs_ni(max_items=80):
    """
    Indeed RSS filtered to Civil Service Jobs domain + NI locations.
    """
    jobs = []
    debug = {"source": "Indeed RSS", "feeds": [], "items_seen": 0, "items_kept": 0}

    queries = [
        "site:civilservicejobs.service.gov.uk Belfast",
        "site:civilservicejobs.service.gov.uk Northern Ireland",
        "site:civilservicejobs.service.gov.uk Lisburn",
        "site:civilservicejobs.service.gov.uk Newry",
        "site:civilservicejobs.service.gov.uk Derry",
    ]

    for q in queries:
        url = f"https://rss.indeed.com/rss?q={quote_plus(q)}&l={quote_plus('Northern Ireland')}"
        debug["feeds"].append(url)

        try:
            feed = fetch_rss(url)
        except Exception as e:
            debug.setdefault("errors", []).append(f"{url} :: {e}")
            continue

        for e in feed.entries:
            debug["items_seen"] += 1
            title = clean(e.get("title", ""))
            link = e.get("link", "")
            summary = clean(re.sub("<.*?>", " ", e.get("summary", "") or ""))

            blob = f"{title}\n{summary}\n{link}"
            if not link:
                continue
            if is_nics(blob):
                continue
            if "civilservicejobs.service.gov.uk" not in link:
                continue
            if not looks_like_ni(blob):
                continue

            jobs.append({
                "source": "UK Civil Service (via Indeed RSS)",
                "title": title or "Untitled",
                "location": "Northern Ireland",
                "url": link,
                "text": blob
            })

            if len(jobs) >= max_items:
                break
        if len(jobs) >= max_items:
            break

    # de-dup
    uniq = {}
    for j in jobs:
        uniq[j["url"]] = j
    jobs = list(uniq.values())
    debug["items_kept"] = len(jobs)

    return jobs, debug

@st.cache_data(ttl=900)
def fetch_careerjet_ni(max_items=80):
    """
    Careerjet RSS, NI location, exclude NICS.
    """
    jobs = []
    debug = {"source": "Careerjet RSS", "feeds": [], "items_seen": 0, "items_kept": 0}

    queries = [
        "HMRC", "Ministry of Justice", "Home Office", "Cabinet Office",
        "civil service", "government", "policy", "analyst", "delivery"
    ]

    for q in queries:
        # Widely used Careerjet RSS pattern:
        url = f"https://rss.careerjet.co.uk/rss?s={quote_plus(q)}&l={quote_plus('Northern Ireland')}&sort=date"
        debug["feeds"].append(url)

        try:
            feed = fetch_rss(url)
        except Exception as e:
            debug.setdefault("errors", []).append(f"{url} :: {e}")
            continue

        for e in feed.entries:
            debug["items_seen"] += 1
            title = clean(e.get("title", ""))
            link = e.get("link", "")
            summary = clean(re.sub("<.*?>", " ", e.get("summary", "") or ""))

            blob = f"{title}\n{summary}\n{link}"
            if not link:
                continue
            if is_nics(blob):
                continue
            if not looks_like_ni(blob):
                continue

            jobs.append({
                "source": "Careerjet RSS",
                "title": title or "Untitled",
                "location": "Northern Ireland",
                "url": link,
                "text": blob
            })

            if len(jobs) >= max_items:
                break
        if len(jobs) >= max_items:
            break

    # de-dup
    uniq = {}
    for j in jobs:
        uniq[j["url"]] = j
    jobs = list(uniq.values())
    debug["items_kept"] = len(jobs)

    return jobs, debug

def score_jobs(cv_text: str, jobs: list[dict]) -> list[dict]:
    """
    Relative scoring so you don't get depressing 0–20% numbers.
    """
    cv_text = clean(cv_text)
    if not cv_text or not jobs:
        return jobs

    docs = [cv_text] + [j["text"] for j in jobs]
    vec = TfidfVectorizer(stop_words="english", max_features=15000)
    X = vec.fit_transform(docs)
    sims = cosine_similarity(X[0:1], X[1:]).flatten()

    # percentile-based "human looking" score range 55–95
    ranks = sims.argsort().argsort()
    n = max(len(sims), 1)
    pct = ranks / max(n - 1, 1)

    scored = []
    for j, p in zip(jobs, pct):
        score = 55 + 40 * float(p)
        j2 = dict(j)
        j2["match_score"] = int(round(min(98, max(50, score))))
        scored.append(j2)

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored


st.title("NI UK Civil Service Job Matcher")
st.caption("UK Civil Service jobs located in Northern Ireland (filters out NICS). RSS-only. Runs on Streamlit Cloud.")

with st.sidebar:
    st.header("Your CV")
    cv_text = st.text_area("Paste your CV (best)", height=220, placeholder="Paste CV text here…")

    st.header("Sources")
    use_indeed = st.checkbox("UK Civil Service (Indeed RSS)", value=True)
    use_careerjet = st.checkbox("Careerjet RSS", value=True)

    st.header("Refresh")
    if st.button("Clear cache"):
        st.cache_data.clear()
        st.success("Cache cleared.")

if st.button("Find matching jobs", type="primary"):
    if not cv_text.strip():
        st.error("Paste your CV text first.")
        st.stop()

    jobs = []
    debug = []

    if use_indeed:
        j, d = fetch_indeed_cs_jobs_ni()
        jobs.extend(j); debug.append(d)

    if use_careerjet:
        j, d = fetch_careerjet_ni()
        jobs.extend(j); debug.append(d)

    # de-dup
    uniq = {}
    for j in jobs:
        uniq[j["url"]] = j
    jobs = list(uniq.values())

    scored = score_jobs(cv_text, jobs)
    st.session_state["results"] = scored
    st.session_state["debug"] = debug


results = st.session_state.get("results", [])
debug = st.session_state.get("debug", [])

st.divider()
st.subheader("Results")

if not results:
    st.info("Run a search to see results.")
else:
    st.write(f"Found **{len(results)}** jobs.")
    show_debug = st.checkbox("Show diagnostics (feeds + counts)", value=False)

    for j in results[:40]:
        with st.container(border=True):
            st.metric("Match", f"{j['match_score']}%")
            st.markdown(f"**{j['title']}**  \n{j['location']}  \n_Source: {j['source']}_")
            st.markdown(f"[Open job]({j['url']})")

    if show_debug:
        st.subheader("Diagnostics")
        for d in debug:
            st.json(d)
        st.caption(
            "If a feed returns 0 items due to blocking or changes, you’ll see it here. "
            "Civil Service Jobs itself can’t be fetched reliably from cloud apps because it requires JS + a bot-check."
        )
