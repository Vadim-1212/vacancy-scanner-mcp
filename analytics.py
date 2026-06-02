import re
from collections import Counter
from statistics import median, quantiles
from typing import Optional

from models import Vacancy, SkillFreq, SkillReport, SalaryReport

SKILLS = [
    # Languages
    "python", "javascript", "typescript", "java", "go", "golang", "rust",
    "c++", "c#", "php", "ruby", "swift", "kotlin", "scala",
    # AI/ML
    "langchain", "langgraph", "llamaindex", "openai", "anthropic",
    "hugging face", "transformers", "rag", "pgvector", "embeddings",
    "llm", "gpt", "claude", "gemini", "mistral",
    "pytorch", "tensorflow", "keras", "scikit-learn", "xgboost",
    "fine-tuning", "rlhf", "nlp", "computer vision", "ml",
    "multi-agent", "ai agents", "mcp", "prompt engineering",
    "vector database", "pinecone", "weaviate", "chroma", "qdrant",
    # Automation
    "n8n", "make", "zapier", "airflow", "prefect", "celery",
    # Backend
    "fastapi", "flask", "django", "express", "spring",
    "rest api", "graphql", "grpc", "websocket",
    # Databases
    "postgresql", "mysql", "sqlite", "mongodb", "redis",
    "elasticsearch", "cassandra", "dynamodb", "bigquery", "snowflake",
    # Cloud / DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "ansible", "github actions", "jenkins", "gitlab ci", "linux", "bash",
    # Data
    "pandas", "numpy", "spark", "kafka", "sql",
    "tableau", "power bi", "grafana",
    # Frontend
    "react", "vue", "angular", "next.js", "html", "css",
    # Other
    "git", "playwright", "selenium", "webscraping", "telegram",
    "microservices", "agile", "scrum",
]


def extract_skills(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for skill in SKILLS:
        if re.search(r"\b" + re.escape(skill) + r"\b", text_lower):
            found.append(skill)
    return found


def _safe_float(s: str) -> Optional[float]:
    try:
        v = float(re.sub(r"\s+", "", s or ""))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def parse_salary_usd(text: str) -> Optional[float]:
    if not text:
        return None
    text = str(text)
    try:
        # K notation: $80K, 100k-150k
        k_vals = [_safe_float(x) for x in re.findall(r"\$?([\d.]+)\s*[Kk]", text)]
        k_vals = [x * 1000 for x in k_vals if x]
        if k_vals:
            return round(sum(k_vals) / len(k_vals))

        # RUB → annual USD (1 USD ≈ 90 RUB)
        if any(x in text for x in ("₽", "руб", "RUB", "rub")):
            clean = [_safe_float(re.sub(r"\s+", "", n)) for n in re.findall(r"[\d\s]+", text)]
            clean = [x for x in clean if x and x > 100]
            if clean:
                avg = sum(clean) / len(clean)
                monthly = avg if avg < 500_000 else avg / 12
                return round(monthly / 90 * 12)

        is_monthly = bool(re.search(r"\b(mo|month|мес)\b", text, re.I))
        vals = [_safe_float(n.replace(",", "")) for n in re.findall(r"[\d,]+", text)]
        vals = [x for x in vals if x and x > 1000]
        if not vals:
            return None
        avg = sum(vals) / len(vals)
        return round(avg * 12 if is_monthly else avg)
    except Exception:
        return None


def dedup(vacancies: list[Vacancy]) -> list[Vacancy]:
    seen: set[tuple] = set()
    result = []
    for v in vacancies:
        key = (v.company.lower()[:20], v.title.lower()[:30])
        if key not in seen:
            seen.add(key)
            result.append(v)
    return result


def build_skill_report(vacancies: list[Vacancy]) -> SkillReport:
    counter: Counter = Counter()
    for v in vacancies:
        text = v.description + " " + " ".join(v.skills)
        for skill in set(extract_skills(text)):
            counter[skill] += 1

    total = len(vacancies)
    top = [
        SkillFreq(skill=s, count=c, percent=round(c / total * 100, 1))
        for s, c in counter.most_common(30)
    ]

    must = [s.skill for s in top[:5]]
    nice = [s.skill for s in top[5:10]]
    rec = f"Обязательно в JD: {', '.join(must)}."
    if nice:
        rec += f" Желательно: {', '.join(nice)}."

    return SkillReport(top_skills=top, total_analyzed=total, recommendation=rec)


def build_salary_report(vacancies: list[Vacancy], sources: list[str]) -> SalaryReport:
    salaries = [v.salary_usd for v in vacancies if v.salary_usd and v.salary_usd > 5_000]
    if not salaries:
        return SalaryReport(sample_size=0, sources=sources)

    salaries.sort()
    try:
        q = quantiles(salaries, n=4)
        p25, p75 = round(q[0]), round(q[2])
    except Exception:
        p25 = p75 = None

    return SalaryReport(
        min=round(min(salaries)),
        median=round(median(salaries)),
        max=round(max(salaries)),
        percentile_25=p25,
        percentile_75=p75,
        sample_size=len(salaries),
        sources=sources,
    )


def score_candidate(vacancy_text: str, skills: list[str], experience_years: int) -> dict:
    required = extract_skills(vacancy_text)
    if not required:
        return {"score_percent": 0, "matched": [], "gaps": [], "verdict": "Не удалось извлечь требования из текста."}

    candidate = [s.lower() for s in skills]
    matched = [s for s in required if any(s in c or c in s for c in candidate)]
    gaps = [s for s in required if s not in matched]

    score = len(matched) / len(required) * 100

    # Penalise experience mismatch
    exp_nums = re.findall(r"(\d+)\+?\s*(?:year|лет|года)", vacancy_text.lower())
    required_exp = max((int(x) for x in exp_nums), default=0)
    if required_exp and experience_years < required_exp:
        score *= 0.8

    score = round(score)

    if score >= 80:
        verdict = f"Отличный кандидат ({score}%). Gap минимальный."
    elif score >= 60:
        verdict = f"Сильный кандидат ({score}%). Gap: {', '.join(gaps[:3])}. Рекомендуем собеседование."
    elif score >= 40:
        verdict = f"Средний match ({score}%). Значительные gaps: {', '.join(gaps[:5])}."
    else:
        verdict = f"Слабый match ({score}%). Кандидат не соответствует основным требованиям."

    return {
        "score_percent": score,
        "matched": matched,
        "gaps": gaps[:10],
        "verdict": verdict,
    }
