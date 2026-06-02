"""Djinni.co — Ukrainian/Eastern Europe IT job board. No auth for read."""
import re

from sources import SEMAPHORE, get_client
from models import Vacancy


def _matches(job: dict, query: str) -> bool:
    q_words = [w.lower() for w in re.split(r"\s+", query.strip()) if len(w) > 2]
    if not q_words:
        return True
    title = (job.get("title") or "").lower()
    desc = re.sub(r"<[^>]+>", " ", job.get("long_description") or "").lower()
    cat = ((job.get("category") or {}).get("name") or "").lower()
    full = title + " " + desc[:300] + " " + cat
    if any(w in title for w in q_words):
        return True
    hits = sum(1 for w in q_words if w in full)
    return hits >= max(1, round(len(q_words) * 0.5))


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []
    offset = 0
    page_size = 50

    while len(results) < limit and offset < 400:
        try:
            async with SEMAPHORE:
                r = await client.get(
                    "https://djinni.co/api/jobs/",
                    params={"limit": page_size, "offset": offset},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            break

        jobs = data.get("results", [])
        if not jobs:
            break

        for j in jobs:
            if remote_only:
                fmt = (j.get("work_format") or "").lower()
                if "remote" not in fmt and "дистанц" not in fmt:
                    continue

            if not _matches(j, query):
                continue

            sal_min = j.get("public_salary_min") or 0
            sal_max = j.get("public_salary_max") or 0
            salary_usd = None
            salary_text = None
            if sal_min or sal_max:
                avg = (sal_min + sal_max) / (2 if sal_min and sal_max else 1)
                salary_usd = round(avg * 12)  # Djinni shows monthly USD
                salary_text = f"${sal_min or '?'}–${sal_max or '?'}/mo"

            skills = [
                (s.get("title") or "").lower()
                for s in (j.get("skills_experience") or [])
                if isinstance(s, dict)
            ]
            slug = j.get("slug", "")
            url = f"https://djinni.co/jobs/{slug}/" if slug else ""

            results.append(Vacancy(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=url,
                source="djinni",
                remote="remote" in (j.get("work_format") or "").lower(),
                salary_text=salary_text,
                salary_usd=salary_usd,
                skills=skills,
                description=re.sub(r"<[^>]+>", " ", j.get("long_description") or "")[:500],
                location=j.get("location", ""),
            ))

            if len(results) >= limit:
                return results

        offset += page_size
        if offset >= data.get("count", 0):
            break

    return results
