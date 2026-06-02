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
}

_DEFAULT_SOURCES = ["hh", "himalayas", "remoteok", "arbeitnow", "jobicy", "habr"]


async def _gather_vacancies(
    query: str,
    sources: list[str],
    limit: int,
    remote_only: bool,
) -> tuple[list, list[str], list[str]]:
    per_source = max(limit // len(sources), 10)

    async def fetch_one(name: str):
        mod = _SOURCE_MAP.get(name)
        if not mod:
            return name, [], f"Unknown source: {name}"
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


# ─── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        asyncio.run(close_client())
