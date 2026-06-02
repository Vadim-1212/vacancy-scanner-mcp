# Vacancy Scanner MCP

Multi-source job market intelligence server for Claude and other MCP-compatible AI agents.

Aggregates vacancies from **HH.ru, Himalayas, RemoteOK, Arbeitnow, Jobicy, Habr Career** (+ optional Adzuna and JSearch). Six sources work out of the box with zero API keys.

## Tools

| Tool | What it does | HR use case |
|------|-------------|-------------|
| `search_vacancies` | Search across all sources with filters | "Find Senior PM remote jobs" |
| `analyze_skills` | Skill frequency in JDs for a role | "What skills to list in a JD?" |
| `salary_benchmark` | Salary ranges (min/median/max/p25/p75) | "What does EU pay for DevOps?" |
| `score_candidate` | Match candidate skills against vacancy text | "Does this resume fit the role?" |
| `top_hiring_companies` | Who is hiring most for a role right now | "Who is actively hiring Go devs?" |

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/vacancy-scanner-mcp
cd vacancy-scanner-mcp
pip install -r requirements.txt
cp .env.example .env
# Edit .env — only HH_APP_TOKEN needed for Russian market
```

Add to your `mcp.json` / `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vacancy-scanner": {
      "command": "python3",
      "args": ["/path/to/vacancy-scanner-mcp/server.py"],
      "env": {
        "HH_APP_TOKEN": "your_token",
        "HH_CLIENT_ID": "your_client_id",
        "HH_CLIENT_SECRET": "your_client_secret",
        "HH_USER_AGENT": "VacancyScanner/1.0 (your@email.com)"
      }
    }
  }
}
```

## Sources

| Source | Auth | Coverage |
|--------|------|----------|
| HH.ru | Free app token ([dev.hh.ru](https://dev.hh.ru)) | Russia / CIS |
| Himalayas | None | Remote global |
| RemoteOK | None | Remote global |
| Arbeitnow | None | Europe |
| Jobicy | None | Remote global |
| Habr Career RSS | None | Russia IT |
| Adzuna | Free key ([developer.adzuna.com](https://developer.adzuna.com/signup)) | US / EU / AU |
| JSearch | Free key ([RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)) | LinkedIn + Indeed + Google Jobs |

## Getting HH.ru credentials

1. Go to [dev.hh.ru](https://dev.hh.ru) → Create Application
2. Copy `client_id` and `client_secret` to `.env`
3. Get app token:
```bash
curl -X POST https://hh.ru/oauth/token \
  -d "grant_type=client_credentials&client_id=YOUR_ID&client_secret=YOUR_SECRET"
```
The server auto-refreshes the token when it expires.

## Requirements

- Python 3.11+
- `fastmcp>=3.3.0`
- `httpx>=0.27.0`
- `pydantic>=2.0.0`
