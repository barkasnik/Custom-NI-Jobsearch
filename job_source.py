# job_source.py

import os
import requests
from bs4 import BeautifulSoup  # kept in case you want it later
import feedparser

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")


def get_adzuna_jobs():
    """
    Fetch jobs from Adzuna limited to Northern Ireland.
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    url = (
        "https://api.adzuna.com/v1/api/jobs/gb/search/1"
        f"?app_id={ADZUNA_APP_ID}"
        f"&app_key={ADZUNA_APP_KEY}"
        f"&where=northern%20ireland"
        f"&results_per_page=50"
        f"&content-type=application/json"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append(
            {
                "title": item.get("title", "Unknown"),
                "company": item.get("company", {}).get("display_name", "Unknown"),
                "location": item.get("location", {}).get("display_name", "Northern Ireland"),
                "salary": item.get("salary_min") or 0,
                "description": item.get("description", ""),
                "url": item.get("redirect_url", ""),
                "source": "Adzuna",
            }
        )
    return jobs


def get_civil_service_jobs_ni():
    """
    Fetch Civil Service jobs via RSS and filter to Northern Ireland.
    """
    feed_url = "https://www.civilservicejobs.service.gov.uk/csr/index.cgi/rss"

    try:
        feed = feedparser.parse(feed_url)
    except Exception:
        return []

    jobs = []
    for entry in feed.entries:
        # Some feeds use custom fields; we guard with .get
        location = getattr(entry, "location", "") or entry.get("location", "")
        if not location:
            # Sometimes location might be in the summary or title, but we keep it simple.
            continue

        if "northern ireland" not in location.lower():
            continue

        title = entry.title
        link = entry.link
        description = getattr(entry, "summary", "") or entry.get("summary", "")

        jobs.append(
            {
                "title": title,
                "company": "Civil Service",
                "location": location,
                "salary": 0,  # RSS doesn’t reliably expose salary
                "description": description,
                "url": link,
                "source": "Civil Service NI",
            }
        )

    return jobs


def get_all_jobs():
    """
    Combine Adzuna and Civil Service NI jobs.
    """
    adzuna_jobs = get_adzuna_jobs()
    civil_jobs = get_civil_service_jobs_ni()
    return adzuna_jobs + civil_jobs
