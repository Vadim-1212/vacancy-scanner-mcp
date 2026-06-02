"""TrudVsem.ru — Russian government open job portal. No auth required."""
from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import parse_salary_usd


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []
    page_size = min(limit, 100)
    offset = 0

    while len(results) < limit:
        params = {"limit": page_size, "offset": offset, "text": query}
        try:
            async with SEMAPHORE:
                r = await client.get(
                    "https://opendata.trudvsem.ru/api/v1/vacancies",
                    params=params,
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            break

        raw = data.get("results", {}).get("vacancies", [])
        if not raw:
            break

        for item in raw:
            v = item.get("vacancy", {})

            if remote_only:
                emp = (v.get("employment") or "").lower()
                if "удалённ" not in emp and "remote" not in emp:
                    continue

            sal_min = v.get("salary_min") or 0
            sal_max = v.get("salary_max") or 0
            salary_usd = None
            salary_text = None
            if sal_min or sal_max:
                rub_avg = (sal_min + sal_max) / (2 if sal_min and sal_max else 1)
                salary_usd = round(rub_avg / 90 * 12)
                salary_text = v.get("salary", "")

            region = (v.get("region") or {}).get("name", "Россия")
            company = (v.get("company") or {}).get("name", "")
            reqs = v.get("requirements", "") or ""
            desc = reqs[:500]

            results.append(Vacancy(
                title=v.get("job-name", ""),
                company=company,
                url=v.get("vac_url", ""),
                source="trudvsem",
                remote=(v.get("employment") or "").lower().startswith("удалённ"),
                salary_text=salary_text,
                salary_usd=salary_usd,
                skills=[],
                description=desc,
                location=region,
            ))

            if len(results) >= limit:
                return results

        total = data.get("meta", {}).get("total", 0)
        offset += page_size
        if offset >= total:
            break

    return results
