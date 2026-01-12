# job_source.py

import os
import requests
from bs4 import BeautifulSoup

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")


def get_adzuna_jobs():
    url = (
        "https://api.adzuna.com/v1/api/jobs/gb/search/1"
        f"?app_id={ADZUNA_APP_ID}"
        f"&app_key={ADZUNA_APP_KEY}"
        f"&where=northern%20ireland"
        f"&results_per_page=50"
        f"&content-type=application/json"
    )

    try:
        resp = requests.get(url)
        data = resp.json()
    except:
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append({
            "title": item.get("title", "Unknown"),
            "company": item.get("company", {}).get("display_name", "Unknown"),
            "location": item.get("location", {}).get("display_name", "Northern Ireland"),
            "salary": item.get("salary_min") or 0,
            "description": item.get("description", ""),
            "url": item.get("redirect_url", ""),
            "source": "Adzuna"
        })
    return jobs


def get_civil_service_jobs_ni():
    url = (
        "https://www.civilservicejobs.service.gov.uk/csr/index.cgi"
        "?action=advanced_search&location=2"
    )

    try:
        resp = requests.get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
    except:
        return []

    jobs = []
    rows = soup.select("div.search-result")

    for row in rows:
        title_tag = row.select_one("a.search-result-title")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")
        if link and not link.startswith("http"):
            link = "https://www.civilservicejobs.service.gov.uk" + link

        org = row.select_one("div.search-result-organisation")
        loc = row.select_one("div.search-result-location")

        jobs.append({
            "title": title,
            "company": org.get_text(strip=True) if org else "Civil Service",
            "location": loc.get_text(strip=True) if loc else "Northern Ireland",
            "salary": 0,
            "description": "Civil Service NI role. See link for details.",
            "url": link,
            "source": "Civil Service NI"
        })

    return jobs


def get_all_jobs():
    return get_adzuna_jobs() + get_civil_service_jobs_ni()
