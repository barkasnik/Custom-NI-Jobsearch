from __future__ import annotations

import io
import re
import html as ihtml
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import feedparser

from pypdf import PdfReader
import docx


# ---------------- HTTP (retries + longer timeouts) ----------------
_SESSION = requests.Session()
_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.7,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    raise_on_status=False,
)
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))
_SESSION.mount("http://", HTTPAdapter(max_retries=_RETRY))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

def _get(url: str, timeout=(10, 60)) -> requests.Response:
    return _SESSION.get(
        url,
        headers={"User-Agent": _UA, "Accept-Language": "en-GB,en;q=0.9"},
        timeout=timeout,
    )

def _strip_html(s: str) -> str:
    s = ihtml.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    summary: str


# ---------------- CV extraction ----------------
def extract_text_from_upload(uploaded_file) -> str:
    name = (uploaded_file.name or "").lower()
    data = uploaded_file.getvalue()
    try:
        if name.endswith(".txt"):
            return data.decode("utf-8", errors="ignore").strip()

        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:20]).strip()

        if name.endswith(".docx"):
            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs).strip()
    except Exception:
        return ""
    return ""


# ---------------- Tokenising + similarity ----------------
_STOP = {
    "the","and","or","a","an","to","of","in","for","on","with","at","by","from","as","is","are","be",
    "this","that","it","you","your","we","our","they","their","will","can","may","not","have","has",
    "i","me","my","he","she","them","but","if","so","than","then","into","over","under","within",
}

def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-\_]{1,}", (text or "").lower())
    return [w for w in words if w not in _STOP and len(w) > 2]

def _similarity(a: str, b: str) -> Tuple[float, List[str]]:
    A = set(_tokens(a))
    B = set(_tokens(b))
    if not B:
        return 0.0, []
    if not A:
        return 0.12, list(B)[:12]
    inter = A.intersection(B)
    sim = len(inter) / max(1.0, (len(A) * len(B)) ** 0.5)
    sim = max(0.0, min(1.0, sim))
    return sim, sorted(inter)[:20]

def _human_score(sim: float) -> int:
    # human-looking band: avoids depressing 0–20% scores
    score = 55 + int(round(40 * (sim ** 0.65)))  # 55..95
    return max(40, min(98, score))


# ---------------- NI + “gov-ish” heuristics ----------------
NI_TERMS = [
    "northern ireland", "belfast", "lisburn", "newry", "derry", "londonderry",
    "carrickfergus", "antrim", "armagh", "omagh", "enniskillen", "coleraine", "ballymena", "bangor"
]

GOV_TERMS = [
    "civil service", "hmrc", "home office", "ministry of justice", "cabinet office",
    "dwp", "defra", "uksv", "security clearance", "operational delivery",
    "success profiles", "crown", "government"
]

NEGATIVE_NOT_UKCS = [
    "civil engineering", "civil construction", "civils", "site engineer"
]

def _looks_ni(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in NI_TERMS)

def _looks_gov(text: str) -> bool:
    t = (text or "").lower()
    if any(x in t for x in NEGATIVE_NOT_UKCS):
        return False
    return any(x in t for x in GOV_TERMS)


# ---------------- RSS fetch helper ----------------
def _fetch_rss(url: str) -> Tuple[List[dict], dict]:
    diag = {"url": url, "status": None, "entries": 0}
    try:
        r = _get(url, timeout=(10, 60))
        diag["status"] = r.status_code
        if r.status_code != 200:
            return [], diag
        feed = feedparser.parse(r.text)
        entries = list(feed.entries or [])
        diag["entries"] = len(entries)
        return entries, diag
    except Exception as e:
        diag["error"] = f"{type(e).__name__}: {e}"
        return [], diag


# ---------------- Sources (RSS only) ----------------
def fetch_careerjet_rss(extra_keywords: str = "", location: str = "Northern Ireland") -> Tuple[List[Job], List[dict]]:
    # Careerjet RSS endpoint is widely used; may still occasionally return 0 depending on query.
    queries = [
        "civil service",
        "government",
        "HMRC",
        "Home Office",
        "Ministry of Justice",
        "Cabinet Office",
        "operational delivery",
        "customer service supervisor",
        "operations supervisor",
    ]
    if extra_keywords:
        queries.insert(0, extra_keywords)

    jobs: List[Job] = []
    diags: List[dict] = []

    for q in queries:
        url = f"https://rss.careerjet.co.uk/rss?s={quote_plus(q)}&l={quote_plus(location)}&sort=date"
        entries, d = _fetch_rss(url)
        diags.append(d)

        for e in entries[:40]:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            summary = _strip_html(e.get("summary") or e.get("description") or "")

            if not link:
                continue

            blob = f"{title}\n{summary}\n{link}"
            if not _looks_ni(blob):
                continue

            jobs.append(Job(
                source="Careerjet RSS",
                title=title or "Untitled",
                company="",
                location=location,
                url=link,
                summary=summary[:700],
            ))

    uniq = {j.url: j for j in jobs if j.url}
    return list(uniq.values()), diags


def fetch_indeed_rss(extra_keywords: str = "", location: str = "Northern Ireland") -> Tuple[List[Job], List[dict]]:
    # Indeed RSS is known to be inconsistent; we treat it as “nice to have”.
    queries = [
        "civil service Belfast",
        "HMRC Belfast",
        "government Belfast",
        "operational delivery Belfast",
        "civil service Northern Ireland",
    ]
    if extra_keywords:
        queries.insert(0, f"{extra_keywords} Belfast")

    jobs: List[Job] = []
    diags: List[dict] = []

    for q in queries:
        url = f"https://rss.indeed.com/rss?q={quote_plus(q)}&l={quote_plus(location)}"
        entries, d = _fetch_rss(url)
        diags.append(d)

        for e in entries[:50]:
            raw_title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            summary = _strip_html(e.get("summary") or e.get("description") or "")

            if not link:
                continue

            blob = f"{raw_title}\n{summary}\n{link}"
            if not _looks_ni(blob):
                continue

            # Indeed titles often: "Title - Company - Location"
            parts = [p.strip() for p in raw_title.split(" - ")]
            title = parts[0] if parts else raw_title
            company = parts[1] if len(parts) >= 2 else ""
            loc = parts[2] if len(parts) >= 3 else location

            jobs.append(Job(
                source="Indeed RSS",
                title=title or "Untitled",
                company=company,
                location=loc,
                url=link,
                summary=summary[:700],
            ))

    uniq = {j.url: j for j in jobs if j.url}
    return list(uniq.values()), diags


# ---------------- Multi-profile CV scoring ----------------
TECH_HINTS = {"python","javascript","html","css","sql","api","github","vscode","software","developer","programming"}
OPS_HINTS  = {"hotel","housekeeping","supervisor","rota","inventory","stock","audit","hygiene","customer","service","training","team"}
SALES_HINTS = {"broker","real","estate","sales","leads","marketing","clients","prospecting","closing","crm"}

def build_cv_profiles(cv_text: str) -> Dict[str, str]:
    lines = [ln.strip() for ln in (cv_text or "").splitlines() if ln.strip()]
    tech, ops, sales = [], [], []

    for ln in lines:
        low = ln.lower()
        toks = set(_tokens(low))
        if toks & TECH_HINTS:
            tech.append(ln)
        if toks & OPS_HINTS:
            ops.append(ln)
        if toks & SALES_HINTS:
            sales.append(ln)

    profiles = {
        "Full CV": cv_text or "",
        "Hospitality / Operations": "\n".join(ops) if ops else "",
        "Sales / Real estate": "\n".join(sales) if sales else "",
        "Tech / Programming": "\n".join(tech) if tech else "",
    }

    # remove empties (but always keep full CV)
    out = {"Full CV": profiles["Full CV"]}
    for k, v in profiles.items():
        if k != "Full CV" and v.strip():
            out[k] = v
    return out


def fetch_all_jobs(
    use_careerjet: bool = True,
    use_indeed: bool = True,
    strict_gov_only: bool = True,
    extra_keywords: str = "",
) -> Tuple[List[Job], Dict]:
    diag: Dict = {"counts": {}, "errors": [], "feeds": []}
    jobs: List[Job] = []

    if use_careerjet:
        try:
            cj, d = fetch_careerjet_rss(extra_keywords=extra_keywords)
            jobs.extend(cj)
            diag["counts"]["Careerjet RSS"] = len(cj)
            diag["feeds"].extend(d)
        except Exception as e:
            diag["counts"]["Careerjet RSS"] = 0
            diag["errors"].append(f"Careerjet RSS failed: {type(e).__name__}: {e}")

    if use_indeed:
        try:
            ij, d = fetch_indeed_rss(extra_keywords=extra_keywords)
            jobs.extend(ij)
            diag["counts"]["Indeed RSS"] = len(ij)
            diag["feeds"].extend(d)
        except Exception as e:
            diag["counts"]["Indeed RSS"] = 0
            diag["errors"].append(f"Indeed RSS failed: {type(e).__name__}: {e}")

    # Dedup by URL
    uniq = {j.url: j for j in jobs if j.url}
    jobs = list(uniq.values())

    # Gov-only filter (but never “force 0”)
    if strict_gov_only and jobs:
        kept = [j for j in jobs if _looks_gov(f"{j.title}\n{j.summary}\n{j.company}\n{j.url}")]
        if kept:
            jobs = kept
            diag["counts"]["Gov-ish kept"] = len(jobs)
        else:
            diag["counts"]["Gov-ish kept"] = 0
            diag["errors"].append("Gov-only filter removed everything; relaxed to show NI jobs from feeds.")

    diag["counts"]["Deduped total"] = len(jobs)
    return jobs, diag


def score_jobs(cv_text: str, jobs: List[Job]) -> List[Dict]:
    profiles = build_cv_profiles(cv_text or "")

    results: List[Dict] = []
    for j in jobs:
        job_text = f"{j.title}\n{j.company}\n{j.location}\n{j.summary}\n{j.url}"

        best = {"sim": 0.0, "why": [], "profile": "Full CV"}
        for name, ptext in profiles.items():
            sim, why = _similarity(ptext, job_text)
            if sim > best["sim"]:
                best = {"sim": sim, "why": why, "profile": name}

        score = _human_score(best["sim"])
        if _looks_gov(job_text):
            score = min(98, score + 3)

        results.append({
            "score": score,
            "why": best["why"],
            "profile": best["profile"],
            "source": j.source,
            "title": j.title,
            "company": j.company,
            "location": j.location,
            "url": j.url,
            "summary": j.summary,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
