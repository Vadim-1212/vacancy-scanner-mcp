"""Himalayas — remote job feed. No server-side search; filters client-side."""
import logging
import re

log = logging.getLogger(__name__)

from sources import SEMAPHORE, get_client
from models import Vacancy


def _matches(job: dict, query: str) -> bool:
    q_words = [w.lower() for w in re.split(r"\s+", query.strip()) if len(w) > 2]
    if not q_words:
        return True
    title = (job.get("title") or "").lower()
    cat_text = " ".join(
        (c.get("name") or c.get("slug") or "") for c in (job.get("categories") or [])
        if isinstance(c, dict)
    ).lower()
    full_text = title + " " + (job.get("excerpt") or "").lower() + " " + cat_text

    # Title match on ANY word → strong signal
    if any(w in title for w in q_words):
        return True
    # Body match requires MAJORITY of words (≥60%)
    hits = sum(1 for w in q_words if w in full_text)
    return hits >= max(1, round(len(q_words) * 0.6))


async def search(query: str, limit: int = 20, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []
    fetch_pages = max(3, (limit // 20) + 2)  # fetch extra pages for client-side filter

    for page_idx in range(fetch_pages):
        params = {"limit": 20, "offset": page_idx * 20}
        try:
            async with SEMAPHORE:
                r = await client.get("https://himalayas.app/jobs/api", params=params, timeout=15)
                r.raise_for_status()
                jobs = r.json().get("jobs", [])
        except Exception as e:
            log.warning("himalayas page %d failed: %s", page_idx, e)
            break

        if not jobs:
            break

        for j in jobs:
            if not _matches(j, query):
                continue

            sal_min = j.get("minSalary") or j.get("annualSalaryMin")
            sal_max = j.get("maxSalary") or j.get("annualSalaryMax")
            salary_usd = None
            salary_text = None
            if sal_min or sal_max:
                vals = [x for x in [sal_min, sal_max] if x]
                salary_usd = round(sum(vals) / len(vals))
                cur = j.get("currency", "USD")
                salary_text = f"{cur} {sal_min or '?'}–{sal_max or '?'}"

            cats = j.get("categories") or []
            skills = [
                (c.get("name") or c.get("slug", "")).lower().replace("-", " ")
                for c in cats if isinstance(c, dict)
            ]

            url = j.get("applicationLink") or j.get("guid") or ""

            results.append(Vacancy(
                title=j.get("title", ""),
                company=j.get("companyName") or j.get("companySlug", ""),
                url=url,
                source="himalayas",
                remote=True,
                salary_text=salary_text,
                salary_usd=salary_usd,
                skills=skills,
                description=(j.get("excerpt") or "")[:500],
                location="Remote",
            ))

            if len(results) >= limit:
                return results

    return results
