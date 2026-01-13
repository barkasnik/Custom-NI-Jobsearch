from __future__ import annotations

import io
import re
import html as ihtml
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote_plus, urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# Optional file parsers (requirements include these)
from pypdf import PdfReader
import docx


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    summary: str
    published: Optional[datetime] = None


# --- Basic text helpers ---

_STOPWORDS = {
    "the","and","or","a","an","to","of","in","for","on","with","at","by","from","as","is","are","be",
    "this","that","it","you","your","we","our","they","their","will","can","may","not","have","has",
    "i","me","my","he","she","them","but","if","so","than","then","into","over","under","within",
}

def _tokens(text: str) -> List[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9][a-z0-9\-\_]{1,}", text)
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def _similarity(cv_text: str, job_text: str) -> Tuple[float, List[str]]:
    """
    Simple token overlap similarity with a 'human-looking' score mapping later.
    Returns: (similarity 0..1, overlapping keywords)
    """
    cv_toks = _tokens(cv_text)
    job_toks = _tokens(job_text)

    if not job_toks:
        return 0.0, []

    cv_set = set(cv_toks)
    job_set = set(job_toks)

    if not cv_set:
        return 0.15, sorted(list(job_set))[:10]  # small baseline if CV empty

    inter = cv_set.intersection(job_set)
    # cosine-ish overlap (binary)
    sim = len(inter) / max(1, (len(cv_set) * len(job_set)) ** 0.5)
    why = sorted(inter)[:20]
    return max(0.0, min(1.0, sim)), why


def _human_score(sim: float, job: Job) -> int:
    """
    Map similarity to a nicer-looking 55..95 range.
    """
    # Base: 55
    # Then add up to +40 depending on sim curve
    curved = sim ** 0.65
    score = 55 + int(round(40 * curved))

    # Small boosts for very relevant signals
    text = f"{job.title} {job.company} {job.summary}".lower()
    if "civil service" in text:
        score += 3
    if any(x in text for x in ["hmrc", "hm revenue", "ministry of justice", "home office", "cabinet office"]):
        score += 2

    return max(40, min(95, score))


# --- Upload parsing ---

def extract_text_from_upload(uploaded_file) -> str:
    name = (uploaded_file.name or "").lower()
    data = uploaded_file.getvalue()

    try:
        if name.endswith(".txt"):
            return data.decode("utf-8", errors="ignore").strip()

        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for p in reader.pages[:20]:  # keep it light
                pages.append(p.extract_text() or "")
            return "\n".join(pages).strip()

        if name.endswith(".docx"):
            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs).strip()
    except Exception:
        # Fall back to empty; app still works without CV
        return ""

    return ""


# --- HTTP helpers ---

def _get(url: str, timeout: int = 20) -> requests.Response:
    # Browser-like headers help avoid simple blocks
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Connection": "keep-alive",
    }
    return requests.get(url, headers=headers, timeout=timeout)


def _strip_html(s: str) -> str:
    s = ihtml.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_relative_time(s: str) -> Optional[datetime]:
    """
    Parse '3 days ago', '21 hours ago', etc.
    """
    s = (s or "").lower().strip()
    m = re.search(r"(\d+)\s+(hour|hours|day|days|week|weeks)\s+ago", s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    now = datetime.now(timezone.utc)
    if "hour" in unit:
        return now - timedelta(hours=n)
    if "day" in unit:
        return now - timedelta(days=n)
    if "week" in unit:
        return now - timedelta(weeks=n)
    return None


# --- Source 1: NIJobs (reliable in practice) ---

NIJOBS_URL = "https://www.nijobs.com/jobs/civil-service/in-northern-ireland"

# Exclude NI Civil Service + NI devolved departments (your “imperial CS” preference)
BLOCK_COMPANY = {
    "ni civil service",
    "northern ireland civil service",
    "department of justice",          # NI DoJ (devolved)
    "department for the economy",     # NI DfE
    "department of health",           # NI DoH
    "department of finance",          # NI DoF
    "daera",                          # NI agriculture/env dept
    "education authority",
}

def fetch_nijobs(limit: int = 80) -> List[Job]:
    r = _get(NIJOBS_URL)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    jobs: List[Job] = []

    # NIJobs listings expose job title links under h2 headings
    for h2 in soup.find_all("h2"):
        a = h2.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "/job/" not in href:
            continue

        title = a.get_text(" ", strip=True)
        url = href if href.startswith("http") else urljoin("https://www.nijobs.com", href)

        # Grab text from the nearest reasonably-sized container
        container = h2.find_parent(["article", "section", "div"]) or h2.parent
        lines = [t.strip() for t in container.stripped_strings if t.strip()]

        # Heuristic: after title -> company -> location -> salary -> snippet -> time
        company = ""
        location = ""
        summary = ""
        published = None

        try:
            idx = lines.index(title)
        except ValueError:
            idx = 0

        # company = next non-noise line
        for i in range(idx + 1, min(idx + 8, len(lines))):
            cand = lines[i]
            low = cand.lower()
            if any(x in low for x in ["£", "per annum", "not disclosed", "new", "more"]):
                continue
            if re.search(r"\d+\s+(hour|day|week)s?\s+ago", low):
                continue
            company = cand
            break

        # location = first line that looks like a location
        for i in range(idx + 1, min(idx + 12, len(lines))):
            cand = lines[i]
            low = cand.lower()
            if "county" in low or re.search(r"\bBT\d{1,2}\b", cand) or "northern ireland" in low:
                location = cand
                break

        # published
        for i in range(idx + 1, min(idx + 20, len(lines))):
            dt = _parse_relative_time(lines[i])
            if dt:
                published = dt
                break

        # summary: pick the first longer sentence-like line after salary/company/location
        for i in range(idx + 1, min(idx + 30, len(lines))):
            cand = lines[i]
            if len(cand) >= 80 and not cand.lower().startswith(("http", "published")):
                summary = cand
                break

        job = Job(
            source="NIJobs",
            title=title,
            company=company,
            location=location,
            url=url,
            summary=summary,
            published=published,
        )

        # Filter out NI Civil Service / devolved NI departments
        comp_low = (job.company or "").lower()
        if any(b in comp_low for b in BLOCK_COMPANY):
            continue

        jobs.append(job)
        if len(jobs) >= limit:
            break

    return jobs


# --- Source 2: Indeed RSS (key-free, best-effort) ---

def fetch_indeed_rss(query: str = "civil service", location: str = "Northern Ireland", limit: int = 60) -> List[Job]:
    url = f"https://rss.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}"
    feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})

    jobs: List[Job] = []

    for e in (feed.entries or [])[:limit]:
        raw_title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        summary = _strip_html(e.get("summary") or e.get("description") or "")

        # Indeed commonly formats: "Job Title - Company - Location"
        parts = [p.strip() for p in raw_title.split(" - ")]
        title = parts[0] if parts else raw_title
        company = parts[1] if len(parts) >= 2 else ""
        loc = parts[2] if len(parts) >= 3 else ""

        published = None
        if e.get("published"):
            try:
                published = dateparser.parse(e["published"])
                if published and published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except Exception:
                published = None

        job = Job(
            source="Indeed RSS",
            title=title,
            company=company,
            location=loc,
            url=link,
            summary=summary,
            published=published,
        )

        # Exclude NI Civil Service / devolved NI departments, same rule
        comp_low = (job.company or "").lower()
        if any(b in comp_low for b in BLOCK_COMPANY):
            continue

        # Must be NI-ish
        loc_low = (job.location or "").lower()
        if not any(x in loc_low for x in ["belfast", "northern ireland", "derry", "londonderry", "lisburn", "newry", "antrim", "tyrone", "fermanagh", "down", "armagh"]):
            continue

        jobs.append(job)

    return jobs


# --- Aggregation + scoring ---

def fetch_all_jobs() -> Tuple[List[Job], Dict]:
    diag = {"counts": {}, "errors": []}
    all_jobs: List[Job] = []

    # NIJobs first (most reliable for “not 0 results”)
    try:
        nij = fetch_nijobs()
        diag["counts"]["NIJobs"] = len(nij)
        all_jobs.extend(nij)
    except Exception as ex:
        diag["counts"]["NIJobs"] = 0
        diag["errors"].append(f"NIJobs failed: {type(ex).__name__}: {ex}")

    # Indeed RSS second (best-effort)
    try:
        inde = fetch_indeed_rss()
        diag["counts"]["Indeed RSS"] = len(inde)
        all_jobs.extend(inde)
    except Exception as ex:
        diag["counts"]["Indeed RSS"] = 0
        diag["errors"].append(f"Indeed RSS failed: {type(ex).__name__}: {ex}")

    # Deduplicate by URL
    seen = set()
    deduped: List[Job] = []
    for j in all_jobs:
        if not j.url or j.url in seen:
            continue
        seen.add(j.url)
        deduped.append(j)

    diag["counts"]["Deduped total"] = len(deduped)
    return deduped, diag


def score_jobs(cv_text: str, jobs: List[Job]) -> List[Dict]:
    results = []
    for j in jobs:
        job_text = f"{j.title}\n{j.company}\n{j.location}\n{j.summary}"
        sim, why = _similarity(cv_text or "", job_text)
        score = _human_score(sim, j)

        results.append(
            {
                "score": score,
                "why": why,
                "source": j.source,
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "url": j.url,
                "summary": j.summary,
                "published": j.published.isoformat() if j.published else "",
            }
        )

    # Sort: score desc, then newest-ish
    def _sort_key(r):
        try:
            dt = dateparser.parse(r.get("published") or "") if r.get("published") else None
        except Exception:
            dt = None
        return (r["score"], dt or datetime(1970, 1, 1, tzinfo=timezone.utc))

    results.sort(key=_sort_key, reverse=True)
    return results
