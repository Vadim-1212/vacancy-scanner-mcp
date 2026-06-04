# Vacancy Scanner MCP

> **Job market intelligence as an MCP server.**  
> Connect to Claude, Cursor, or any MCP client — and search, analyze and score jobs across 9 sources with a single tool call.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/protocol-MCP-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Sources](https://img.shields.io/badge/job%20sources-9%20built--in-orange.svg)](#sources)

---

## The problem

Researching a job market manually is slow:

```
Open HH.ru → search → scroll → open 20 tabs → copy requirements into spreadsheet
→ switch to RemoteOK → repeat → normalize salaries → compare with resume
→ 4–6 hours later: a messy spreadsheet and decision fatigue
```

**This server does that in ~15 seconds.**

---

## What it does

An MCP server that exposes job market data as callable tools for LLM agents.

```
Claude / Cursor / any MCP client
         │
         ▼
┌─────────────────────────────┐
│     vacancy-scanner MCP     │
│                             │
│  search_vacancies           │  ◄── 9 sources in parallel
│  analyze_skills             │  ◄── skill frequency from JDs
│  salary_benchmark           │  ◄── min / median / max / p25 / p75
│  score_candidate            │  ◄── resume vs JD match %
│  top_hiring_companies       │  ◄── who is actively hiring
│  add_source / remove_source │  ◄── plug in any new board
└─────────────────────────────┘
         │
         ▼
HH.ru · Himalayas · RemoteOK · Arbeitnow · Jobicy
Habr Career · TrudVsem · WeWorkRemotely · [+ Adzuna / JSearch optional]
```

---

## Tools

| Tool | Input | Output |
|------|-------|--------|
| `search_vacancies` | query, sources, limit | vacancies list with salary, skills, remote flag |
| `analyze_skills` | role | top-30 skills with frequency %, JD recommendation |
| `salary_benchmark` | role, market (ru/us/eu/global) | min/median/max/p25/p75 in USD |
| `score_candidate` | vacancy_text, skills[], years | match %, matched skills, gaps, verdict |
| `top_hiring_companies` | role | ranked companies with vacancy count + avg salary |
| `list_sources` | — | all configured sources and credential status |
| `add_source` | url, field_map, auth | adds any JSON API or RSS board dynamically |
| `remove_source` | name | removes custom source |
| `check_sources` | — | pings all sources, shows latency and health |
| `refresh_tokens` | — | re-fetches HH.ru OAuth token |

---

## Sample output

<details>
<summary><b>search_vacancies("AI automation engineer", limit=5)</b></summary>

```json
{
  "total": 5,
  "sources_ok": ["hh", "himalayas", "remoteok", "arbeitnow"],
  "sources_failed": [],
  "vacancies": [
    {
      "title": "AI Automation Engineer",
      "company": "Purrweb",
      "url": "https://hh.ru/vacancy/123456789",
      "source": "hh",
      "remote": true,
      "salary_text": "150 000 – 220 000 ₽",
      "salary_usd": 42000,
      "location": "Remote",
      "skills": ["python", "langchain", "n8n", "openai", "fastapi", "docker"]
    },
    {
      "title": "LLM Workflow Engineer",
      "company": "Synthflow AI",
      "url": "https://himalayas.app/jobs/synthflow-llm-engineer",
      "source": "himalayas",
      "remote": true,
      "salary_text": "$80K – $120K",
      "salary_usd": 100000,
      "location": "Remote (EU)",
      "skills": ["python", "langchain", "openai", "rag", "fastapi"]
    }
  ]
}
```
</details>

<details>
<summary><b>analyze_skills("AI automation developer")</b></summary>

```json
{
  "total_analyzed": 147,
  "recommendation": "Обязательно в JD: python, openai, langchain, n8n, docker. Желательно: fastapi, rag, postgresql, git, prompt engineering.",
  "top_skills": [
    {"skill": "python",            "count": 139, "percent": 94.6},
    {"skill": "openai",            "count": 121, "percent": 82.3},
    {"skill": "langchain",         "count": 108, "percent": 73.5},
    {"skill": "n8n",               "count": 97,  "percent": 66.0},
    {"skill": "docker",            "count": 91,  "percent": 61.9},
    {"skill": "fastapi",           "count": 83,  "percent": 56.5},
    {"skill": "rag",               "count": 79,  "percent": 53.7},
    {"skill": "postgresql",        "count": 74,  "percent": 50.3},
    {"skill": "git",               "count": 68,  "percent": 46.3},
    {"skill": "prompt engineering","count": 61,  "percent": 41.5}
  ]
}
```
</details>

<details>
<summary><b>salary_benchmark("AI automation engineer", market="ru")</b></summary>

```json
{
  "currency": "USD",
  "min": 14400,
  "percentile_25": 21600,
  "median": 30000,
  "percentile_75": 40800,
  "max": 72000,
  "sample_size": 34,
  "sources": ["hh", "habr"]
}
```
</details>

<details>
<summary><b>score_candidate(vacancy_text, skills=["python","n8n","openai api","docker","git"])</b></summary>

```json
{
  "score_percent": 74,
  "matched": ["python", "n8n", "openai", "docker", "git"],
  "gaps": ["langchain", "fastapi", "rag", "postgresql"],
  "verdict": "Сильный кандидат (74%). Gap: langchain, fastapi, rag. Рекомендуем собеседование."
}
```
</details>

---

## Quick start

```bash
git clone https://github.com/Vadim-1212/vacancy-scanner-mcp
cd vacancy-scanner-mcp
pip install -r requirements.txt
cp .env.example .env        # fill in HH token (others are optional)
python server.py            # starts MCP server on stdio
```

Add to your `claude_desktop_config.json` or `mcp.json`:

```json
{
  "mcpServers": {
    "vacancy-scanner": {
      "command": "python3",
      "args": ["/absolute/path/to/vacancy-scanner-mcp/server.py"],
      "env": {
        "HH_APP_TOKEN": "your_token",
        "HH_USER_AGENT": "VacancyScanner/1.0 (your@email.com)"
      }
    }
  }
}
```

Then in Claude: *"Find AI automation jobs remote, show salary ranges and what skills I'm missing"* — done.

---

## Sources

| Source | Auth | Geography |
|--------|------|-----------|
| HH.ru | Free token — [dev.hh.ru](https://dev.hh.ru) | Russia / CIS |
| Himalayas | None | Remote global |
| RemoteOK | None | Remote global |
| Arbeitnow | None | Europe |
| Jobicy | None | Remote global |
| Habr Career RSS | None | Russia IT |
| TrudVsem.ru | None | Russia (govt portal) |
| WeWorkRemotely | None | Remote global |
| Adzuna *(optional)* | Free key — [developer.adzuna.com](https://developer.adzuna.com/signup) | US / EU / AU / CA |
| JSearch *(optional)* | Free key — [RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) | LinkedIn + Indeed + Google Jobs |

**No API key required** for 8 out of 10 sources.  
Add any board in 30 seconds with `add_source`.

---

## How it was built

**Problem framing first.** Before writing code I mapped the manual HR research process (AS IS): HR opens 4–5 tabs, copies data to a spreadsheet, normalizes salaries by hand, compares with requirements manually — 4–6 hours per research cycle.

**Then the automated flow (TO BE):**
```
query → parallel fetch from N sources → deduplicate → normalize salary to USD
      → extract skills from JD text → score against candidate profile
      → return structured JSON
```

**Key engineering decisions:**
- `asyncio.gather` for parallel source fetching — all sources hit simultaneously, not sequentially
- Per-source 30s timeout with graceful degradation — one slow source doesn't block others
- Salary normalization handles: `₽/month`, `$80K`, `€60K–90K`, plain numbers
- Deduplication by `(company[:20], title[:30])` key — catches same job posted on multiple boards
- `add_source` tool: any REST JSON API or RSS feed can be added at runtime without code changes
- Schema validation on all tool outputs via Pydantic — MCP clients always get well-typed data

**QA approach:**  
Each source adapter was tested manually before integration: probe the API endpoint, check field names in the response, map edge cases (missing salary, null skills, pagination). Validation is baked in — if a source returns garbage, it's logged and excluded from results rather than crashing the tool.

---

## Project structure

```
vacancy-scanner-mcp/
├── server.py            # MCP server, all 10 tools
├── analytics.py         # skill extraction, salary parsing, dedup, scoring
├── models.py            # Pydantic schemas: Vacancy, SkillReport, SalaryReport
├── sources/
│   ├── hh.py            # HH.ru with OAuth auto-refresh
│   ├── himalayas.py
│   ├── remoteok.py
│   ├── arbeitnow.py
│   ├── jobicy.py
│   ├── habr.py          # RSS feed parser
│   ├── trudvsem.py
│   ├── weworkremotely.py
│   ├── adzuna.py        # optional, free key
│   ├── jsearch.py       # optional, LinkedIn+Indeed+Google Jobs
│   └── custom.py        # dynamic source loader from custom_sources.json
├── .env.example
└── requirements.txt
```

---

## Requirements

- Python 3.11+
- `fastmcp >= 3.3.0`
- `httpx >= 0.27.0`
- `pydantic >= 2.0.0`

---

## License

MIT
