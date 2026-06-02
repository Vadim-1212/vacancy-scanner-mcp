from sources import SEMAPHORE, get_client
from models import Vacancy


async def search(query: str, limit: int = 20, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []

    for page in range(0, min(limit, 60), 20):
        params = {"search": query, "limit": 20, "offset": page}
        try:
            async with SEMAPHORE:
                r = await client.get("https://himalayas.app/jobs/api", params=params, timeout=15)
                r.raise_for_status()
                jobs = r.json().get("jobs", [])
        except Exception:
            break

        if not jobs:
            break

        for j in jobs:
            sal_min = j.get("annualSalaryMin") or j.get("salaryMin")
            sal_max = j.get("annualSalaryMax") or j.get("salaryMax")
            salary_usd = None
            salary_text = None
            if sal_min or sal_max:
                vals = [x for x in [sal_min, sal_max] if x]
                salary_usd = round(sum(vals) / len(vals))
                salary_text = f"${sal_min or '?'}-${sal_max or '?'}"

            company = j.get("company") or {}
            company_name = company.get("name", "") if isinstance(company, dict) else str(company)

            cats = j.get("categories") or []
            skills = [c.get("slug", "").replace("-", " ") for c in cats if isinstance(c, dict)]

            results.append(Vacancy(
                title=j.get("title", ""),
                company=company_name,
                url=j.get("url", j.get("applicationUrl", "")),
                source="himalayas",
                remote=True,
                salary_text=salary_text,
                salary_usd=salary_usd,
                skills=skills,
                description=j.get("excerpt", "")[:500],
                location="Remote",
            ))

        if len(results) >= limit:
            break

    return results[:limit]
