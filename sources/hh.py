import asyncio
import os
import re

from sources import SEMAPHORE, get_client
from models import Vacancy

_TOKEN = os.getenv("HH_APP_TOKEN", "")
_UA = os.getenv("HH_USER_AGENT", "VacancyScanner/1.0 (user@example.com)")
_CLIENT_ID = os.getenv("HH_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET", "")
_BASE = "https://api.hh.ru"

# Mutable token (refreshed at runtime)
_current_token: list[str] = [_TOKEN]


async def _refresh_token() -> bool:
    return await refresh_token()


async def refresh_token() -> bool:
    """Fetch a new app token via client_credentials. Returns True on success."""
    if not _CLIENT_ID or not _CLIENT_SECRET:
        return False
    client = get_client()
    try:
        r = await client.post(
            "https://hh.ru/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json().get("access_token", "")
        if token:
            _current_token[0] = token
            return True
    except Exception:
        pass
    return False


def token_preview() -> str:
    t = _current_token[0]
    return f"{t[:8]}...{t[-4:]}" if len(t) > 12 else ("set" if t else "not set")


def has_credentials() -> bool:
    return bool(_CLIENT_ID and _CLIENT_SECRET)


def _headers() -> dict:
    h = {"HH-User-Agent": _UA}
    if _current_token[0]:
        h["Authorization"] = f"Bearer {_current_token[0]}"
    return h


def _parse_salary(d: dict) -> tuple[str | None, float | None]:
    sal = d.get("salary") or {}
    if not sal:
        return None, None
    lo = sal.get("from")
    hi = sal.get("to")
    cur = sal.get("currency", "RUB")
    if not lo and not hi:
        return None, None
    text = f"{lo or ''}-{hi or ''} {cur}".strip("-").strip()
    vals = [x for x in (lo, hi) if x]
    avg = sum(vals) / len(vals) if vals else 0
    usd = None
    if avg:
        if cur == "RUB":
            usd = round(avg / 90 * 12)
        elif cur in ("USD", "EUR"):
            usd = round(avg * 12 if avg < 30_000 else avg)
    return text, usd


async def _fetch_detail(vacancy_id: str) -> dict | None:
    client = get_client()
    try:
        async with SEMAPHORE:
            r = await client.get(f"{_BASE}/vacancies/{vacancy_id}", headers=_headers(), timeout=10)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


async def search(query: str, limit: int = 100, remote_only: bool = False) -> list[Vacancy]:
    client = get_client()
    params: dict = {"text": query, "per_page": min(limit, 100), "page": 0}
    if remote_only:
        params["schedule"] = "remote"

    try:
        async with SEMAPHORE:
            r = await client.get(f"{_BASE}/vacancies", params=params, headers=_headers(), timeout=15)
            if r.status_code == 403 and await _refresh_token():
                r = await client.get(f"{_BASE}/vacancies", params=params, headers=_headers(), timeout=15)
            r.raise_for_status()
            items = r.json().get("items", [])
    except Exception:
        return []

    detail_sem = asyncio.Semaphore(5)

    async def enrich(item: dict) -> Vacancy | None:
        async with detail_sem:
            d = await _fetch_detail(item["id"])
        if not d:
            return None
        salary_text, salary_usd = _parse_salary(d)
        skills = [s["name"].lower() for s in (d.get("key_skills") or [])]
        desc = re.sub(r"<[^>]+>", " ", d.get("description", "") or "")
        schedule = (d.get("schedule") or {}).get("id", "")
        area = (d.get("area") or {}).get("name", "")
        return Vacancy(
            title=d.get("name", ""),
            company=(d.get("employer") or {}).get("name", ""),
            url=d.get("alternate_url", ""),
            source="hh",
            remote=schedule == "remote",
            salary_text=salary_text,
            salary_usd=salary_usd,
            skills=skills,
            description=desc[:600],
            location=area,
        )

    results = await asyncio.gather(*[enrich(item) for item in items[:limit]])
    return [v for v in results if v is not None]
