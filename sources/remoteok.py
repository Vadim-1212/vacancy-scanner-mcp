import re

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import parse_salary_usd

# Map common query terms to RemoteOK tag slugs
_TAG_MAP = {
    "ai": "ai", "ml": "machine-learning", "machine learning": "machine-learning",
    "llm": "llm", "langchain": "langchain", "python": "python",
    "javascript": "javascript", "typescript": "typescript", "react": "react",
    "node": "nodejs", "java": "java", "go": "golang", "golang": "golang",
    "rust": "rust", "devops": "devops", "docker": "docker",
    "aws": "aws", "gcp": "gcp", "azure": "azure",
    "data": "data-science", "data science": "data-science",
    "backend": "backend", "frontend": "frontend", "fullstack": "fullstack",
    "agent": "ai", "automation": "automation", "engineer": "engineer",
    "developer": "developer", "dev": "developer",
}


def _query_to_tags(query: str) -> str:
    """Convert a natural language query to RemoteOK comma-separated tags."""
    q_lower = query.lower()
    tags = []
    # Try multi-word tags first
    for phrase, tag in sorted(_TAG_MAP.items(), key=lambda x: -len(x[0])):
        if phrase in q_lower and tag not in tags:
            tags.append(tag)
    # Fallback: use first word
    if not tags:
        first = re.sub(r"[^a-z0-9]", "", query.split()[0].lower())
        tags = [first] if first else ["developer"]
    return ",".join(tags[:3])


def _client_filter(jobs: list[dict], query: str) -> list[dict]:
    """Keep only jobs where title or tags contain at least one query word."""
    q_words = [w.lower() for w in re.split(r"\s+", query) if len(w) > 2]
    if not q_words:
        return jobs
    result = []
    for j in jobs:
        text = (j.get("position", "") + " " + " ".join(j.get("tags") or [])).lower()
        if any(w in text for w in q_words):
            result.append(j)
    return result


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    tags = _query_to_tags(query)
    url = f"https://remoteok.com/api?tags={tags}"

    try:
        async with SEMAPHORE:
            r = await client.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    # First item is metadata object, skip it
    jobs = [j for j in data if isinstance(j, dict) and j.get("position")]
    jobs = _client_filter(jobs, query)

    results = []
    for j in jobs[:limit]:
        sal_min = j.get("salary_min") or 0
        sal_max = j.get("salary_max") or 0
        salary_usd = None
        salary_text = None
        if sal_min or sal_max:
            salary_usd = round((sal_min + sal_max) / (2 if sal_min and sal_max else 1))
            salary_text = f"${sal_min}–${sal_max}" if sal_min and sal_max else f"${sal_min or sal_max}"

        tags_list = j.get("tags") or []
        skills = [t.lower() for t in tags_list if isinstance(t, str)]

        results.append(Vacancy(
            title=j.get("position", ""),
            company=j.get("company", ""),
            url=j.get("url", ""),
            source="remoteok",
            remote=True,
            salary_text=salary_text,
            salary_usd=salary_usd,
            skills=skills,
            description=(j.get("description") or "")[:500],
            location="Remote",
        ))

    return results
