import logging

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills

log = logging.getLogger(__name__)


def _matches(job: dict, query: str) -> bool:
    q_words = set(query.lower().split())
    text = (job.get("title", "") + " " + job.get("description", "")).lower()
    return any(w in text for w in q_words)


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    results = []

    for page in range(1, 10):
        params: dict = {"page": page}
        if remote_only:
            params["remote"] = "true"

        try:
            async with SEMAPHORE:
                r = await client.get(
                    "https://www.arbeitnow.com/api/job-board-api",
                    params=params, timeout=15,
                )
                r.raise_for_status()
                jobs = r.json().get("data", [])
        except Exception as e:
            log.warning("arbeitnow page %d failed: %s", page, e)
            break

        if not jobs:
            break

        for j in jobs:
            if not _matches(j, query):
                continue
            if remote_only and not j.get("remote"):
                continue

            tags = j.get("tags") or []
            skills = [t.lower() for t in tags if isinstance(t, str)]
            desc = j.get("description", "")
            if not skills:
                skills = extract_skills(desc)

            results.append(Vacancy(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                url=j.get("url", ""),
                source="arbeitnow",
                remote=bool(j.get("remote")),
                salary_text=None,
                salary_usd=None,
                skills=skills,
                description=desc[:500],
                location=j.get("location", ""),
            ))

            if len(results) >= limit:
                return results

    return results
