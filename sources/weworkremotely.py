"""WeWorkRemotely — RSS feed, no auth required."""
import re
import xml.etree.ElementTree as ET

from sources import SEMAPHORE, get_client
from models import Vacancy

_FEEDS = [
    "https://weworkremotely.com/remote-jobs.rss",
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]


def _matches(text: str, query: str) -> bool:
    q_words = [w.lower() for w in re.split(r"\s+", query.strip()) if len(w) > 2]
    if not q_words:
        return True
    t = text.lower()
    return any(w in t for w in q_words)


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []

    for feed_url in _FEEDS:
        if len(results) >= limit:
            break
        try:
            async with SEMAPHORE:
                r = await client.get(feed_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                root = ET.fromstring(r.text)
        except Exception:
            continue

        for item in root.findall("./channel/item"):
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc_raw = item.findtext("description") or ""
            desc_clean = re.sub(r"<[^>]+>", " ", desc_raw).strip()

            full_text = title + " " + desc_clean
            if not _matches(full_text, query):
                continue

            # WWR titles: "Company: Job Title"
            if ": " in title:
                company, job_title = title.split(": ", 1)
            else:
                company, job_title = "", title

            results.append(Vacancy(
                title=job_title.strip(),
                company=company.strip(),
                url=link,
                source="weworkremotely",
                remote=True,
                salary_text=None,
                salary_usd=None,
                skills=[],
                description=desc_clean[:500],
                location="Remote",
            ))

            if len(results) >= limit:
                return results

    return results
