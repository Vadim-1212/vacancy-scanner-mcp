"""Optional Adzuna source. Requires ADZUNA_APP_ID and ADZUNA_APP_KEY env vars.
Free registration: https://developer.adzuna.com/signup
"""
import logging
import os

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills

log = logging.getLogger(__name__)

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
        except Exception as e:
            log.warning("adzuna page %d failed: %s", page, e)
            break

        if not jobs:
            break

        # Adzuna salaries are in local currency; approximate to USD (annual)
        _FX = {"us": 1.0, "gb": 1.27, "de": 1.08, "fr": 1.08, "au": 0.65, "ca": 0.74}
        fx = _FX.get(country, 1.0)
        for j in jobs:
            sal_min = j.get("salary_min")
            sal_max = j.get("salary_max")
            sal_vals = [x for x in (sal_min, sal_max) if x]
            salary_usd = round(sum(sal_vals) / len(sal_vals) * fx) if sal_vals else None
            salary_text = f"{sal_min or '?'}–{sal_max or '?'}" if sal_vals else None
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
