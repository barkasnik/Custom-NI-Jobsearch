# job_source.py

import feedparser
import urllib.parse


def _parse_indeed_feed(url):
    feed = feedparser.parse(url)
    jobs = []

    for entry in feed.entries:
        title = entry.title
        link = entry.link
        summary = getattr(entry, "summary", "") or entry.get("summary", "")

        # Indeed often includes location in the summary/title; keep it simple.
        # We'll just tag these as "Northern Ireland" since feed is already NI-targeted.
        location = "Northern Ireland"

        jobs.append(
            {
                "title": title,
                "company": "Indeed",
                "location": location,
                "salary": 0,
                "description": summary,
                "url": link,
                "source": "Indeed",
            }
        )

    return jobs


def get_indeed_jobs_ni():
    """
    Fetch jobs from Indeed via RSS, scoped to Northern Ireland.
    This uses the UK Indeed RSS endpoint with location 'Northern Ireland'.
    """
    base_url = "https://www.indeed.co.uk/rss"
    params = {
        "q": "",  # empty query = all jobs
        "l": "Northern Ireland",
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return _parse_indeed_feed(url)


def get_civil_service_jobs_ni():
    """
    Fetch Civil Service jobs via UK-wide RSS, then filter to locations in Northern Ireland.
    """
    feed_url = "https://www.civilservicejobs.service.gov.uk/csr/index.cgi/rss"

    feed = feedparser.parse(feed_url)
    jobs = []

    for entry in feed.entries:
        # Location may appear as a custom field or inside the summary/title.
        location = getattr(entry, "location", "") or entry.get("location", "")
        summary = getattr(entry, "summary", "") or entry.get("summary", "")
        title = entry.title
        link = entry.link

        text_for_location = " ".join([title, summary, location]).lower()

        if "northern ireland" not in text_for_location and "belfast" not in text_for_location:
            continue

        jobs.append(
            {
                "title": title,
                "company": "Civil Service",
                "location": location if location else "Northern Ireland",
                "salary": 0,
                "description": summary,
                "url": link,
                "source": "Civil Service (UK-wide, NI roles)",
            }
        )

    return jobs


def get_all_jobs():
    """
    Combine Indeed NI and Civil Service UK-wide (filtered to NI) jobs.
    No API keys needed.
    """
    indeed_jobs = get_indeed_jobs_ni()
    civil_jobs = get_civil_service_jobs_ni()
    return indeed_jobs + civil_jobs
