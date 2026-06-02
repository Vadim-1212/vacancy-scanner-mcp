from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills, parse_salary_usd


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    tag = query.split()[0].lower()
    params = {"count": min(limit, 50), "tag": tag}

    try:
        async with SEMAPHORE:
            r = await client.get("https://jobicy.com/api/v2/remote-jobs", params=params, timeout=15)
            r.raise_for_status()
            jobs = r.json().get("jobs", [])
    except Exception:
        return []

    results = []
    for j in jobs[:limit]:
        sal_text = j.get("annualSalaryMin") or j.get("jobSalary")
        salary_usd = parse_salary_usd(str(sal_text)) if sal_text else None
        salary_text = str(sal_text) if sal_text else None

        desc = j.get("jobDescription", "") or j.get("jobExcerpt", "")
        skills = extract_skills(desc)

        results.append(Vacancy(
            title=j.get("jobTitle", ""),
            company=j.get("companyName", ""),
            url=j.get("url", ""),
            source="jobicy",
            remote=True,
            salary_text=salary_text,
            salary_usd=salary_usd,
            skills=skills,
            description=desc[:500],
            location="Remote",
        ))

    return results
