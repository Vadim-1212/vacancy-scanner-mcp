"""
Generic source engine — runs any job board configured via add_source tool.
Configs are persisted to custom_sources.json next to this package.
"""
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from sources import SEMAPHORE, get_client
from models import Vacancy
from analytics import extract_skills, parse_salary_usd

_CONFIG_PATH = Path(__file__).parent.parent / "custom_sources.json"


# ─── Config persistence ───────────────────────────────────────────────────────

def load_configs() -> dict[str, dict]:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def save_configs(configs: dict[str, dict]) -> None:
    _CONFIG_PATH.write_text(json.dumps(configs, indent=2, ensure_ascii=False))


def add_config(cfg: dict) -> None:
    configs = load_configs()
    configs[cfg["name"]] = cfg
    save_configs(configs)


def remove_config(name: str) -> bool:
    configs = load_configs()
    if name not in configs:
        return False
    del configs[name]
    save_configs(configs)
    return True


# ─── Field resolver (dot notation) ────────────────────────────────────────────

def _get(data: dict, path: str):
    """Resolve 'a.b.c' dot notation against a dict. Returns None if missing."""
    if not path:
        return None
    node = data
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit():
            node = node[int(part)]
        else:
            return None
    return node


def _coerce_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "remote")
    return False


def _build_vacancy(item: dict, cfg: dict, source_name: str) -> Vacancy | None:
    fm = cfg.get("field_map", {})

    title = str(_get(item, fm.get("title", "title")) or "").strip()
    if not title:
        return None

    company_raw = _get(item, fm.get("company", "company"))
    company = (
        company_raw.get("name", "") if isinstance(company_raw, dict)
        else str(company_raw or "")
    )

    url = str(_get(item, fm.get("url", "url")) or "")
    description = str(_get(item, fm.get("description", "description")) or "")[:600]

    sal_raw = _get(item, fm.get("salary", "salary"))
    salary_usd = parse_salary_usd(str(sal_raw)) if sal_raw else None
    salary_text = str(sal_raw) if sal_raw else None

    skills_raw = _get(item, fm.get("skills", "skills"))
    if isinstance(skills_raw, list):
        skills = [str(s).lower() for s in skills_raw if s]
    elif isinstance(skills_raw, str):
        skills = [skills_raw.lower()]
    else:
        skills = extract_skills(description)

    remote_raw = _get(item, fm.get("remote", "remote"))
    remote = _coerce_bool(remote_raw) if remote_raw is not None else cfg.get("always_remote", False)

    location_raw = _get(item, fm.get("location", "location"))
    location = (
        location_raw.get("name", "") if isinstance(location_raw, dict)
        else str(location_raw or "")
    )

    return Vacancy(
        title=title,
        company=company,
        url=url,
        source=source_name,
        remote=remote,
        salary_text=salary_text,
        salary_usd=salary_usd,
        skills=skills,
        description=description,
        location=location,
    )


# ─── Auth builder ─────────────────────────────────────────────────────────────

def _build_auth(cfg: dict) -> tuple[dict, dict]:
    """Returns (extra_headers, extra_params)."""
    auth_type = cfg.get("auth_type", "none")
    key_name = cfg.get("auth_key_name", "")
    key_value = cfg.get("auth_key_value", "") or os.getenv(cfg.get("auth_env_var", ""), "")

    headers: dict = {}
    params: dict = {}

    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {key_value}"
    elif auth_type == "api_key_header":
        headers[key_name] = key_value
    elif auth_type == "api_key_query":
        params[key_name] = key_value
    elif auth_type == "basic":
        import base64
        token = base64.b64encode(f"{key_name}:{key_value}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    # Static extra headers from config
    for k, v in (cfg.get("extra_headers") or {}).items():
        headers[k] = v

    return headers, params


# ─── JSON API source ───────────────────────────────────────────────────────────

async def _search_json(cfg: dict, query: str, limit: int, remote_only: bool) -> list[Vacancy]:
    client = get_client()
    extra_headers, auth_params = _build_auth(cfg)

    # Build query params from template
    raw_params = dict(cfg.get("query_params") or {})
    params: dict = {}
    for k, v in raw_params.items():
        if isinstance(v, str):
            params[k] = v.replace("{query}", query).replace("{limit}", str(limit))
        else:
            params[k] = v
    params.update(auth_params)

    if remote_only and cfg.get("remote_param"):
        params[cfg["remote_param"]] = cfg.get("remote_param_value", "true")

    try:
        async with SEMAPHORE:
            r = await client.get(cfg["url"], params=params, headers=extra_headers, timeout=15)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    # Navigate to items array
    items_path = cfg.get("response_items_path", "")
    items = _get(data, items_path) if items_path else data
    if not isinstance(items, list):
        return []

    results = []
    for item in items[:limit]:
        v = _build_vacancy(item, cfg, cfg["name"])
        if v:
            results.append(v)
    return results


# ─── RSS source ────────────────────────────────────────────────────────────────

async def _search_rss(cfg: dict, query: str, limit: int, remote_only: bool) -> list[Vacancy]:
    from urllib.parse import quote
    client = get_client()
    extra_headers, _ = _build_auth(cfg)

    url = cfg["url"].replace("{query}", quote(query)).replace("{limit}", str(limit))

    try:
        async with SEMAPHORE:
            r = await client.get(url, headers={**extra_headers, "Accept": "application/rss+xml, */*"}, timeout=15)
            r.raise_for_status()
            root = ET.fromstring(r.text)
    except Exception:
        return []

    channel = root.find("channel") or root
    results = []
    for item in channel.findall("item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not title:
            continue
        salary_usd = parse_salary_usd(title + " " + desc)
        results.append(Vacancy(
            title=title,
            company=item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "",
            url=link,
            source=cfg["name"],
            remote="remote" in desc.lower() or "удалённ" in desc.lower(),
            salary_text=None,
            salary_usd=salary_usd,
            skills=extract_skills(desc),
            description=desc[:500],
            location=None,
        ))
    return results


# ─── Public search entry point ────────────────────────────────────────────────

async def search(
    name: str,
    query: str,
    limit: int = 50,
    remote_only: bool = False,
) -> list[Vacancy]:
    configs = load_configs()
    cfg = configs.get(name)
    if not cfg:
        return []
    source_type = cfg.get("type", "json_api")
    if source_type == "rss":
        return await _search_rss(cfg, query, limit, remote_only)
    return await _search_json(cfg, query, limit, remote_only)
