#!/usr/bin/env python3
"""
Vacancy Scanner MCP Server
Multi-source job market intelligence: HH.ru, Himalayas, RemoteOK, Arbeitnow, Jobicy, Habr Career.
Optional: Adzuna (global), JSearch (LinkedIn+Indeed+Google Jobs aggregator).
"""
import asyncio
import sys
import os

# Add project root to path so imports work when run directly
sys.path.insert(0, os.path.dirname(__file__))

from fastmcp import FastMCP

import sources.hh as _hh
import sources.himalayas as _himalayas
import sources.remoteok as _remoteok
import sources.arbeitnow as _arbeitnow
import sources.jobicy as _jobicy
import sources.habr as _habr
import sources.adzuna as _adzuna
import sources.jsearch as _jsearch
import sources.custom as _custom
import sources.trudvsem as _trudvsem
import sources.weworkremotely as _weworkremotely
import sources.djinni as _djinni

from analytics import build_skill_report, build_salary_report, score_candidate as _score_candidate, dedup
from sources import close_client

mcp = FastMCP(
    "vacancy-scanner",
    instructions=(
        "Job market intelligence server. Use search_vacancies to find jobs, "
        "analyze_skills to research what skills appear in JDs for a role, "
        "salary_benchmark to get pay ranges, score_candidate to match a resume to a vacancy, "
        "top_hiring_companies to see who is actively recruiting."
    ),
)

_SOURCE_MAP = {
    "hh": _hh,
    "himalayas": _himalayas,
    "remoteok": _remoteok,
    "arbeitnow": _arbeitnow,
    "jobicy": _jobicy,
    "habr": _habr,
    "adzuna": _adzuna,
    "jsearch": _jsearch,
    "trudvsem": _trudvsem,
    "weworkremotely": _weworkremotely,
    "djinni": _djinni,
}

_DEFAULT_SOURCES = ["hh", "himalayas", "remoteok", "arbeitnow", "jobicy", "habr", "trudvsem", "weworkremotely", "djinni"]


def _all_sources() -> list[str]:
    """Built-in defaults + any configured custom sources."""
    custom_names = list(_custom.load_configs().keys())
    return _DEFAULT_SOURCES + [n for n in custom_names if n not in _DEFAULT_SOURCES]


async def _gather_vacancies(
    query: str,
    sources: list[str],
    limit: int,
    remote_only: bool,
) -> tuple[list, list[str], list[str]]:
    per_source = max(limit // max(len(sources), 1), 10)

    async def fetch_one(name: str):
        # Built-in source
        mod = _SOURCE_MAP.get(name)
        if mod:
            try:
                result = await asyncio.wait_for(
                    mod.search(query, limit=per_source, remote_only=remote_only),
                    timeout=30,
                )
                return name, result, None
            except asyncio.TimeoutError:
                return name, [], "timeout"
            except Exception as e:
                return name, [], str(e)

        # Custom source
        if name in _custom.load_configs():
            try:
                result = await asyncio.wait_for(
                    _custom.search(name, query, limit=per_source, remote_only=remote_only),
                    timeout=30,
                )
                return name, result, None
            except asyncio.TimeoutError:
                return name, [], "timeout"
            except Exception as e:
                return name, [], str(e)

        return name, [], f"Unknown source: {name}"

    outcomes = await asyncio.gather(*[fetch_one(s) for s in sources])

    all_vacancies = []
    sources_ok = []
    sources_failed = []
    for name, vacancies, error in outcomes:
        if error:
            sources_failed.append(f"{name}: {error}")
        else:
            sources_ok.append(name)
            all_vacancies.extend(vacancies)

    all_vacancies = dedup(all_vacancies)
    return all_vacancies[:limit], sources_ok, sources_failed


# ─── Tool 1: search_vacancies ──────────────────────────────────────────────────

@mcp.tool()
async def search_vacancies(
    query: str,
    sources: list[str] | None = None,
    limit: int = 50,
    remote_only: bool = False,
) -> dict:
    """Search job vacancies across multiple job boards.

    Args:
        query: Job title or keywords, e.g. "Senior Python Engineer" or "AI automation developer".
        sources: Sources to search. Options: hh, himalayas, remoteok, arbeitnow, jobicy, habr, adzuna, jsearch.
                 Defaults to all configured sources.
        limit: Maximum number of results to return (10–200).
        remote_only: If True, filter for remote-only positions.

    Returns:
        JSON with vacancies list, source status, and total count.
    """
    src = sources or _DEFAULT_SOURCES
    vacancies, ok, failed = await _gather_vacancies(query, src, limit, remote_only)

    return {
        "vacancies": [v.model_dump() for v in vacancies],
        "total": len(vacancies),
        "sources_ok": ok,
        "sources_failed": failed,
    }


# ─── Tool 2: analyze_skills ────────────────────────────────────────────────────

@mcp.tool()
async def analyze_skills(
    role: str,
    sources: list[str] | None = None,
    limit: int = 200,
) -> dict:
    """Analyze skill frequency across job listings for a given role.
    Useful for writing job descriptions, understanding market requirements,
    or benchmarking a candidate's skillset against what employers want.

    Args:
        role: Job role to analyze, e.g. "Product Manager", "DevOps Engineer", "Data Scientist".
        sources: Sources to pull data from. Defaults to all.
        limit: Number of vacancies to analyze (more = better accuracy). Recommended: 100–300.

    Returns:
        Top skills with frequency counts and a JD recommendation.
    """
    src = sources or _DEFAULT_SOURCES
    vacancies, ok, failed = await _gather_vacancies(role, src, limit, remote_only=False)

    if not vacancies:
        return {
            "top_skills": [],
            "total_analyzed": 0,
            "recommendation": "No vacancies found. Try broader query or different sources.",
            "sources_ok": ok,
            "sources_failed": failed,
        }

    report = build_skill_report(vacancies)
    return {
        **report.model_dump(),
        "sources_ok": ok,
        "sources_failed": failed,
    }


# ─── Tool 3: salary_benchmark ──────────────────────────────────────────────────

@mcp.tool()
async def salary_benchmark(
    role: str,
    market: str = "global",
) -> dict:
    """Get salary benchmarks for a role in a specific market.
    Returns min/median/max and percentiles in USD.

    Args:
        role: Job title to benchmark, e.g. "Senior DevOps Engineer".
        market: Target market. Options: "global", "ru" (Russia), "us", "eu".
                "global" uses all available sources; "ru" prioritizes HH.ru; "us"/"eu" use Adzuna+JSearch.

    Returns:
        Salary statistics in USD: min, median, max, p25, p75, sample size.
    """
    market_sources = {
        "ru": ["hh", "habr"],
        "us": ["himalayas", "remoteok", "adzuna", "jsearch"],
        "eu": ["arbeitnow", "adzuna", "himalayas"],
        "global": _DEFAULT_SOURCES,
    }
    src = market_sources.get(market, _DEFAULT_SOURCES)

    vacancies, ok, _ = await _gather_vacancies(role, src, 200, remote_only=False)
    report = build_salary_report(vacancies, ok)

    result = report.model_dump()
    if report.sample_size == 0:
        result["note"] = "No salary data found. Many job listings omit salary — try 'global' market or different role name."
    return result


# ─── Tool 4: score_candidate ───────────────────────────────────────────────────

@mcp.tool()
async def score_candidate(
    vacancy_text: str,
    skills: list[str],
    experience_years: int = 0,
) -> dict:
    """Score how well a candidate matches a job vacancy.
    Extracts required skills from the vacancy text and compares against candidate's skills.

    Args:
        vacancy_text: Full text of the job description (paste the JD here).
        skills: List of candidate's skills, e.g. ["Python", "FastAPI", "Docker", "SQL"].
        experience_years: Candidate's years of relevant experience.

    Returns:
        Match score (0–100%), matched skills, skill gaps, and hiring recommendation.
    """
    return _score_candidate(vacancy_text, skills, experience_years)


# ─── Tool 5: top_hiring_companies ──────────────────────────────────────────────

@mcp.tool()
async def top_hiring_companies(
    role: str,
    limit: int = 20,
    sources: list[str] | None = None,
) -> dict:
    """Find which companies are currently hiring the most for a given role.
    Useful for competitive intelligence, sourcing, or understanding market activity.

    Args:
        role: Job role to research, e.g. "Frontend Developer", "ML Engineer".
        limit: Number of top companies to return.
        sources: Sources to scan. Defaults to all configured sources.

    Returns:
        Ranked list of companies with vacancy count and average salary.
    """
    from collections import Counter, defaultdict

    src = sources or _DEFAULT_SOURCES
    vacancies, ok, failed = await _gather_vacancies(role, src, 300, remote_only=False)

    company_count: Counter = Counter()
    company_salary: defaultdict = defaultdict(list)

    for v in vacancies:
        if v.company:
            company_count[v.company] += 1
            if v.salary_usd:
                company_salary[v.company].append(v.salary_usd)

    companies = []
    for company, count in company_count.most_common(limit):
        salaries = company_salary[company]
        avg_sal = round(sum(salaries) / len(salaries)) if salaries else None
        companies.append({
            "company": company,
            "vacancy_count": count,
            "avg_salary_usd": avg_sal,
        })

    return {
        "companies": companies,
        "total_vacancies_scanned": len(vacancies),
        "sources_ok": ok,
        "sources_failed": failed,
    }


# ─── Tool 6: list_sources ──────────────────────────────────────────────────────

@mcp.tool()
def list_sources() -> dict:
    """List all available job sources: built-in and custom ones added via add_source.

    Returns:
        Built-in sources (always available), custom sources (user-defined),
        and which optional sources have credentials configured.
    """
    custom = _custom.load_configs()
    return {
        "builtin": {
            "hh":             {"desc": "HH.ru — Russia/CIS",                   "auth": "token",   "configured": bool(_hh.token_preview() != "not set")},
            "himalayas":      {"desc": "Himalayas — Remote global",             "auth": "none",    "configured": True},
            "remoteok":       {"desc": "RemoteOK — Remote global",              "auth": "none",    "configured": True},
            "arbeitnow":      {"desc": "Arbeitnow — Europe",                    "auth": "none",    "configured": True},
            "jobicy":         {"desc": "Jobicy — Remote global",                "auth": "none",    "configured": True},
            "habr":           {"desc": "Habr Career RSS — Russia IT",           "auth": "none",    "configured": True},
            "trudvsem":       {"desc": "TrudVsem.ru — Russia govt portal",      "auth": "none",    "configured": True},
            "weworkremotely": {"desc": "WeWorkRemotely — Remote global RSS",    "auth": "none",    "configured": True},
            "djinni":         {"desc": "Djinni.co — Ukraine/Eastern Europe IT", "auth": "none",    "configured": True},
            "adzuna":         {"desc": "Adzuna — US/EU/AU/CA (optional)",       "auth": "api_key", "configured": bool(_adzuna._APP_ID)},
            "jsearch":        {"desc": "JSearch — LinkedIn+Indeed+Google Jobs", "auth": "api_key", "configured": bool(_jsearch._API_KEY)},
        },
        "custom": {
            name: {
                "display_name": cfg.get("display_name", name),
                "url": cfg.get("url", ""),
                "type": cfg.get("type", "json_api"),
                "auth_type": cfg.get("auth_type", "none"),
            }
            for name, cfg in custom.items()
        },
        "total": 11 + len(custom),
    }


# ─── Tool 7: add_source ────────────────────────────────────────────────────────

@mcp.tool()
def add_source(
    name: str,
    url: str,
    source_type: str = "json_api",
    display_name: str = "",
    query_param: str = "q",
    limit_param: str = "limit",
    response_items_path: str = "",
    field_title: str = "title",
    field_company: str = "company",
    field_url: str = "url",
    field_description: str = "description",
    field_salary: str = "salary",
    field_skills: str = "skills",
    field_remote: str = "remote",
    field_location: str = "location",
    always_remote: bool = False,
    auth_type: str = "none",
    auth_key_name: str = "",
    auth_key_value: str = "",
    auth_env_var: str = "",
    extra_headers: dict | None = None,
    remote_param: str = "",
    remote_param_value: str = "true",
    extra_query_params: dict | None = None,
) -> dict:
    """Add a new job board source to the scanner. Works for any REST JSON API or RSS feed.
    The source is saved to custom_sources.json and immediately available in all tools.

    Args:
        name: Unique identifier, e.g. "weworkremotely" (no spaces).
        url: Base URL of the API or RSS feed. Use {query} and {limit} as placeholders in the URL
             (for RSS) or in extra_query_params (for JSON APIs).
        source_type: "json_api" or "rss".
        display_name: Human-readable name shown in reports.
        query_param: Query parameter name for the search term, e.g. "q", "search", "keywords".
        limit_param: Query parameter name for result count, e.g. "limit", "per_page", "count".
        response_items_path: Dot-notation path to the jobs array in the JSON response,
                             e.g. "data", "jobs", "results.items". Leave empty if root is the array.
        field_title: JSON field name for job title, e.g. "title", "job_title", "position".
        field_company: Field for company name. Supports dot notation: "employer.name".
        field_url: Field for application URL.
        field_description: Field for job description text.
        field_salary: Field for salary (text or number), e.g. "salary", "compensation".
        field_skills: Field for skills list (array of strings), e.g. "tags", "required_skills".
        field_remote: Boolean field for remote flag, e.g. "is_remote", "remote".
        field_location: Field for location string, e.g. "location", "city".
        always_remote: Set True if this board only lists remote jobs (no per-job remote field needed).
        auth_type: Authentication method: "none", "bearer", "api_key_header", "api_key_query", "basic".
        auth_key_name: Header name (for api_key_header/basic) or query param name (for api_key_query).
        auth_key_value: The key/token value. Leave empty and use auth_env_var instead for security.
        auth_env_var: Environment variable name to read the auth value from, e.g. "MYBOARD_API_KEY".
        extra_headers: Additional static headers as dict, e.g. {"User-Agent": "Mozilla/5.0"}.
        remote_param: Query param to filter remote jobs, e.g. "remote", "is_remote".
        remote_param_value: Value for remote_param, default "true".
        extra_query_params: Additional static query params always added to requests.

    Returns:
        Confirmation with the saved config and a test result.

    Examples:
        # WeWorkRemotely RSS:
        add_source(name="wwr", url="https://weworkremotely.com/remote-jobs.rss", source_type="rss",
                   display_name="We Work Remotely", always_remote=True)

        # Generic JSON board with API key:
        add_source(name="myboard", url="https://api.myboard.com/jobs", query_param="search",
                   response_items_path="data.jobs", field_title="job_title",
                   field_company="employer.name", auth_type="api_key_query",
                   auth_key_name="api_key", auth_env_var="MYBOARD_API_KEY")
    """
    if not name.replace("_", "").replace("-", "").isalnum():
        return {"error": "name must contain only letters, digits, underscores, hyphens"}
    if name in _SOURCE_MAP:
        return {"error": f"'{name}' is a built-in source and cannot be overridden"}

    cfg: dict = {
        "name": name,
        "display_name": display_name or name,
        "url": url,
        "type": source_type,
        "query_params": {
            query_param: "{query}",
            limit_param: "{limit}",
        },
        "response_items_path": response_items_path,
        "field_map": {
            "title":       field_title,
            "company":     field_company,
            "url":         field_url,
            "description": field_description,
            "salary":      field_salary,
            "skills":      field_skills,
            "remote":      field_remote,
            "location":    field_location,
        },
        "always_remote": always_remote,
        "auth_type":     auth_type,
        "auth_key_name": auth_key_name,
        "auth_key_value": auth_key_value,
        "auth_env_var":  auth_env_var,
        "extra_headers": extra_headers or {},
        "remote_param":  remote_param,
        "remote_param_value": remote_param_value,
    }
    if extra_query_params:
        cfg["query_params"].update(extra_query_params)

    _custom.add_config(cfg)
    return {
        "status": "added",
        "name": name,
        "config": cfg,
        "hint": f"Source '{name}' is now available. Run search_vacancies with sources=['{name}'] to test.",
    }


# ─── Tool 8: remove_source ─────────────────────────────────────────────────────

@mcp.tool()
def remove_source(name: str) -> dict:
    """Remove a custom source added via add_source.
    Built-in sources (hh, himalayas, remoteok, etc.) cannot be removed.

    Args:
        name: Source identifier to remove, as shown in list_sources.

    Returns:
        Confirmation or error if source not found.
    """
    if name in _SOURCE_MAP:
        return {"error": f"'{name}' is a built-in source and cannot be removed"}
    ok = _custom.remove_config(name)
    if ok:
        return {"status": "removed", "name": name}
    return {"error": f"Source '{name}' not found in custom sources"}


# ─── Tool 9: check_sources ──────────────────────────────────────────────────────

# Minimal probes per source: (url, params, extra_headers)
_SOURCE_PROBES: dict[str, tuple[str, dict, dict]] = {
    "hh":        ("https://api.hh.ru/vacancies",                    {"text": "python", "per_page": 1}, {}),
    "himalayas": ("https://himalayas.app/jobs/api",                  {"search": "python", "limit": 1}, {}),
    "remoteok":  ("https://remoteok.com/api",                        {"tags": "python"},                {"User-Agent": "Mozilla/5.0"}),
    "arbeitnow": ("https://www.arbeitnow.com/api/job-board-api",     {"page": 1},                       {}),
    "jobicy":    ("https://jobicy.com/api/v2/remote-jobs",           {"count": 1, "tag": "python"},     {}),
    "habr":      ("https://career.habr.com/vacancies/rss",           {"q": "python"},                   {"Accept": "application/rss+xml"}),
    "trudvsem":       ("https://opendata.trudvsem.ru/api/v1/vacancies",          {"limit": 1, "text": "python"},   {}),
    "weworkremotely": ("https://weworkremotely.com/remote-jobs.rss",              {},                               {"User-Agent": "Mozilla/5.0"}),
    "djinni":         ("https://djinni.co/api/jobs/",                             {"limit": 1},                     {}),
    "adzuna":    ("https://api.adzuna.com/v1/api/jobs/us/search/1",  {"app_id": _adzuna._APP_ID or "x", "app_key": _adzuna._APP_KEY or "x", "what": "python", "results_per_page": 1}, {}),
    "jsearch":   ("https://jsearch.p.rapidapi.com/search",           {"query": "python", "num_pages": "1"}, {"X-RapidAPI-Key": _jsearch._API_KEY or "", "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}),
}


@mcp.tool()
async def check_sources() -> dict:
    """Check connectivity and health of all configured job sources.

    Tests each source with a minimal request and reports response time,
    HTTP status, and whether credentials are present.
    Use this before running large searches to diagnose issues.

    Returns:
        Per-source status (ok/error/timeout/no_key), response time in ms,
        credential status, and an overall summary.
    """
    import time
    from sources import get_client, HEADERS as _BASE_HEADERS

    client = get_client()

    async def probe(name: str) -> tuple[str, dict]:
        url, params, extra_headers = _SOURCE_PROBES[name]

        # Skip optional sources if no key
        if name == "adzuna" and not _adzuna._APP_ID:
            return name, {"status": "no_key", "note": "Set ADZUNA_APP_ID + ADZUNA_APP_KEY in env"}
        if name == "jsearch" and not _jsearch._API_KEY:
            return name, {"status": "no_key", "note": "Set JSEARCH_API_KEY in env"}

        # HH needs auth headers
        req_headers = {**_BASE_HEADERS, **extra_headers}
        if name == "hh":
            req_headers.update(_hh._headers())

        t0 = time.monotonic()
        try:
            async with asyncio.timeout(10):
                r = await client.get(url, params=params, headers=req_headers, timeout=10)
            elapsed = round((time.monotonic() - t0) * 1000)
            ok = r.status_code < 400
            return name, {
                "status": "ok" if ok else "error",
                "http_status": r.status_code,
                "response_ms": elapsed,
                "error": r.text[:120] if not ok else None,
            }
        except asyncio.TimeoutError:
            return name, {"status": "timeout", "response_ms": 10_000, "error": "no response in 10s"}
        except Exception as e:
            return name, {"status": "error", "response_ms": None, "error": str(e)[:120]}

    outcomes = await asyncio.gather(*[probe(name) for name in _SOURCE_PROBES])
    sources_result = dict(outcomes)

    ok_count = sum(1 for v in sources_result.values() if v["status"] == "ok")
    total = len(sources_result)

    return {
        "sources": sources_result,
        "summary": f"{ok_count}/{total} sources healthy",
        "credentials": {
            "hh": f"token {_hh.token_preview()}, can_refresh={_hh.has_credentials()}",
            "adzuna": "configured" if _adzuna._APP_ID else "not set (optional — global market)",
            "jsearch": "configured" if _jsearch._API_KEY else "not set (optional — LinkedIn/Indeed/Google Jobs)",
        },
    }


# ─── Tool 7: refresh_tokens ────────────────────────────────────────────────────

@mcp.tool()
async def refresh_tokens() -> dict:
    """Refresh and validate API credentials for all sources.

    HH.ru: automatically fetches a new token via client_credentials (no user action needed).
    Adzuna / JSearch: validates existing key with a live test request.
    No-auth sources (Himalayas, RemoteOK, etc.): confirms connectivity.

    Use this when searches return empty results or sources show errors in check_sources.

    Returns:
        Per-source credential status and whether refresh succeeded.
    """
    from sources import get_client

    client = get_client()
    results: dict[str, dict] = {}

    # ── HH.ru: auto-refresh token ──────────────────────────────────────────────
    if _hh.has_credentials():
        ok = await _hh.refresh_token()
        results["hh"] = {
            "status": "refreshed" if ok else "refresh_failed",
            "token": _hh.token_preview(),
            "note": "New token active" if ok else "Check HH_CLIENT_ID / HH_CLIENT_SECRET",
        }
    elif _hh.token_preview() != "not set":
        results["hh"] = {
            "status": "static_token",
            "token": _hh.token_preview(),
            "note": "Token set but no client credentials — cannot auto-refresh. "
                    "Add HH_CLIENT_ID + HH_CLIENT_SECRET to enable auto-refresh.",
        }
    else:
        results["hh"] = {
            "status": "no_credentials",
            "note": "Set HH_APP_TOKEN (and HH_CLIENT_ID + HH_CLIENT_SECRET for auto-refresh) in env",
        }

    # ── Adzuna: validate key ────────────────────────────────────────────────────
    if _adzuna._APP_ID and _adzuna._APP_KEY:
        try:
            async with asyncio.timeout(10):
                r = await client.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={"app_id": _adzuna._APP_ID, "app_key": _adzuna._APP_KEY,
                            "what": "engineer", "results_per_page": 1},
                    timeout=10,
                )
            results["adzuna"] = {
                "status": "ok" if r.status_code == 200 else "invalid",
                "http_status": r.status_code,
                "note": "Key valid" if r.status_code == 200 else r.text[:100],
            }
        except Exception as e:
            results["adzuna"] = {"status": "error", "note": str(e)[:100]}
    else:
        results["adzuna"] = {
            "status": "no_key",
            "note": "Optional. Register free at https://developer.adzuna.com/signup",
        }

    # ── JSearch: validate key ───────────────────────────────────────────────────
    if _jsearch._API_KEY:
        try:
            async with asyncio.timeout(10):
                r = await client.get(
                    "https://jsearch.p.rapidapi.com/search",
                    params={"query": "engineer", "num_pages": "1"},
                    headers={"X-RapidAPI-Key": _jsearch._API_KEY,
                             "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                    timeout=10,
                )
            results["jsearch"] = {
                "status": "ok" if r.status_code == 200 else "invalid",
                "http_status": r.status_code,
                "note": "Key valid" if r.status_code == 200 else r.text[:100],
            }
        except Exception as e:
            results["jsearch"] = {"status": "error", "note": str(e)[:100]}
    else:
        results["jsearch"] = {
            "status": "no_key",
            "note": "Optional. Free tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch",
        }

    # ── No-auth sources: quick connectivity ping ────────────────────────────────
    no_auth = {
        "himalayas": ("https://himalayas.app/jobs/api", {"search": "python", "limit": 1}),
        "remoteok":  ("https://remoteok.com/api",       {"tags": "python"}),
        "arbeitnow": ("https://www.arbeitnow.com/api/job-board-api", {"page": 1}),
        "jobicy":    ("https://jobicy.com/api/v2/remote-jobs", {"count": 1, "tag": "python"}),
        "habr":      ("https://career.habr.com/vacancies/rss", {"q": "python"}),
    }

    async def ping(name: str, url: str, params: dict) -> tuple[str, dict]:
        try:
            async with asyncio.timeout(8):
                r = await client.get(url, params=params, timeout=8)
            return name, {"status": "ok" if r.status_code < 400 else "error",
                          "http_status": r.status_code, "note": "No auth needed"}
        except asyncio.TimeoutError:
            return name, {"status": "timeout", "note": "No response in 8s"}
        except Exception as e:
            return name, {"status": "error", "note": str(e)[:80]}

    pings = await asyncio.gather(*[ping(n, u, p) for n, (u, p) in no_auth.items()])
    results.update(dict(pings))

    ok = sum(1 for v in results.values() if v["status"] in ("ok", "refreshed", "static_token"))
    return {
        "credentials": results,
        "summary": f"{ok}/{len(results)} sources ready",
        "action_needed": [
            k for k, v in results.items()
            if v["status"] in ("no_key", "no_credentials", "invalid", "refresh_failed")
        ],
    }


# ─── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        asyncio.run(close_client())
