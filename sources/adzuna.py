"""Optional Adzuna source. Requires ADZUNA_APP_ID and ADZUNA_APP_KEY env vars.
Free registration: https://developer.adzuna.com/signup
"""
import os

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills, parse_salary_usd

_APP_ID = os.getenv("ADZUNA_APP_ID", "")
_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

COUNTRY_FOR_MARKET = {"ru": "ru", "us": "us", "eu": "gb", "gb": "gb", "global": "us"}


async def search(
    query: str,
    limit: int = 50,
    remote_only: bool = False,
    market: str = "global",
) -> list[Vacancy]:
    if not _APP_ID or not _APP_KEY:
        return []

    client = get_client()
    country = COUNTRY_FOR_MARKET.get(market, "us")
    results = []

    for page in range(1, 5):
        params = {
            "app_id": _APP_ID,
            "app_key": _APP_KEY,
            "what": query,
            "results_per_page": min(50, limit),
            "page": page,
        }
        if remote_only:
            params["what_and"] = "remote"

        try:
            async with SEMAPHORE:
                r = await client.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                    params=params, timeout=15,
                )
                r.raise_for_status()
                jobs = r.json().get("results", [])
        except Exception:
            break

        if not jobs:
            break

        for j in jobs:
            sal = j.get("salary_min") or j.get("salary_max")
            salary_usd = round(float(sal)) if sal else None
            salary_text = f"£{j.get('salary_min', '')}-{j.get('salary_max', '')}" if sal else None
            desc = j.get("description", "")
            skills = extract_skills(desc)

            results.append(Vacancy(
                title=j.get("title", ""),
                company=(j.get("company") or {}).get("display_name", ""),
                url=j.get("redirect_url", ""),
                source="adzuna",
                remote="remote" in desc.lower() or "remote" in j.get("title", "").lower(),
                salary_text=salary_text,
                salary_usd=salary_usd,
                skills=skills,
                description=desc[:500],
                location=(j.get("location") or {}).get("display_name", ""),
            ))

            if len(results) >= limit:
                return results

    return results
