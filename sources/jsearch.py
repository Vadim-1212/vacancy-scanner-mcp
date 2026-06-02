"""Optional JSearch source (aggregates LinkedIn, Indeed, Google Jobs).
Requires JSEARCH_API_KEY from RapidAPI: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Free tier available, no credit card required.
"""
import os

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills, parse_salary_usd

_API_KEY = os.getenv("JSEARCH_API_KEY", "")


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    if not _API_KEY:
        return []

    client = get_client()
    params = {
        "query": query + (" remote" if remote_only else ""),
        "num_pages": min((limit // 10) + 1, 5),
        "page": "1",
    }
    headers = {
        "X-RapidAPI-Key": _API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    try:
        async with SEMAPHORE:
            r = await client.get(
                "https://jsearch.p.rapidapi.com/search",
                params=params, headers=headers, timeout=20,
            )
            r.raise_for_status()
            jobs = r.json().get("data", [])
    except Exception:
        return []

    results = []
    for j in jobs[:limit]:
        sal_min = j.get("job_min_salary")
        sal_max = j.get("job_max_salary")
        salary_usd = None
        salary_text = None
        if sal_min or sal_max:
            vals = [x for x in [sal_min, sal_max] if x]
            salary_usd = round(sum(vals) / len(vals))
            salary_text = f"${sal_min or '?'}-${sal_max or '?'} {j.get('job_salary_currency', 'USD')}"

        desc = j.get("job_description", "")
        skills = extract_skills(desc)

        results.append(Vacancy(
            title=j.get("job_title", ""),
            company=j.get("employer_name", ""),
            url=j.get("job_apply_link", ""),
            source="jsearch",
            remote=bool(j.get("job_is_remote")),
            salary_text=salary_text,
            salary_usd=salary_usd,
            skills=skills,
            description=desc[:500],
            location=f"{j.get('job_city', '')}, {j.get('job_country', '')}".strip(", "),
        ))

    return results
