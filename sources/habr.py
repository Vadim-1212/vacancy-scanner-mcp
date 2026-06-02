import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills, parse_salary_usd

log = logging.getLogger(__name__)


async def search(query: str, limit: int = 50, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    encoded = quote(query)
    url = f"https://career.habr.com/vacancies/rss?q={encoded}"
    if remote_only:
        url += "&type=all&locations[]=remote"

    try:
        async with SEMAPHORE:
            r = await client.get(url, timeout=15, headers={"Accept": "application/rss+xml, application/xml, */*"})
            r.raise_for_status()
            root = ET.fromstring(r.text)
    except Exception as e:
        log.warning("habr fetch failed: %s", e)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    results = []
    for item in channel.findall("item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()

        sal_text = None
        salary_usd = None
        sal_match = re.search(r"([\d\s]+[₽$€]|от\s+[\d\s]+)", title + " " + desc)
        if sal_match:
            sal_text = sal_match.group(0).strip()
            salary_usd = parse_salary_usd(sal_text)

        skills = extract_skills(desc)

        results.append(Vacancy(
            title=title,
            company="",
            url=link,
            source="habr",
            remote="удалённ" in desc.lower() or "remote" in desc.lower(),
            salary_text=sal_text,
            salary_usd=salary_usd,
            skills=skills,
            description=desc[:500],
            location=None,
        ))

    return results
