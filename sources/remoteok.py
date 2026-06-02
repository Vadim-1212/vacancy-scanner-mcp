from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import parse_salary_usd


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    # RemoteOK tag-based: use first keyword as tag
    tag = query.split()[0].lower().replace("+", "").replace("#", "")
    url = f"https://remoteok.com/api?tags={tag}"

    try:
        async with SEMAPHORE:
            r = await client.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    # First item is metadata
    jobs = [j for j in data if isinstance(j, dict) and j.get("position")]
    results = []

    for j in jobs[:limit]:
        sal_min = j.get("salary_min") or 0
        sal_max = j.get("salary_max") or 0
        salary_usd = None
        salary_text = None
        if sal_min or sal_max:
            salary_usd = round((sal_min + sal_max) / (2 if sal_min and sal_max else 1))
            salary_text = f"${sal_min}-${sal_max}" if sal_min and sal_max else f"${sal_min or sal_max}"

        tags = j.get("tags") or []
        skills = [t.lower() for t in tags if isinstance(t, str)]

        results.append(Vacancy(
            title=j.get("position", ""),
            company=j.get("company", ""),
            url=j.get("url", ""),
            source="remoteok",
            remote=True,
            salary_text=salary_text,
            salary_usd=salary_usd,
            skills=skills,
            description=j.get("description", "")[:500],
            location="Remote",
        ))

    return results
