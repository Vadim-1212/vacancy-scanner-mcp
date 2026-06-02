from pydantic import BaseModel, Field
from typing import Optional


class Vacancy(BaseModel):
    title: str
    company: str
    url: str
    source: str
    remote: bool = False
    salary_text: Optional[str] = None
    salary_usd: Optional[float] = None
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    location: Optional[str] = None


class SkillFreq(BaseModel):
    skill: str
    count: int
    percent: float


class SkillReport(BaseModel):
    top_skills: list[SkillFreq]
    total_analyzed: int
    recommendation: str


class SalaryReport(BaseModel):
    currency: str = "USD"
    min: Optional[float] = None
    median: Optional[float] = None
    max: Optional[float] = None
    percentile_25: Optional[float] = None
    percentile_75: Optional[float] = None
    sample_size: int = 0
    sources: list[str] = []
