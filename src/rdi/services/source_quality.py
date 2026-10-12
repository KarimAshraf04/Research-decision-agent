"""Source-quality scoring (bonus: feeds the evaluator and the report's evidence weighting)."""
from __future__ import annotations

from datetime import date

TYPE_SCORES = {
    "peer_reviewed": 0.90,
    "official_docs": 0.80,
    "industry_report": 0.75,
    "news": 0.60,
    "blog": 0.35,
    "vendor_marketing": 0.35,
    "forum": 0.25,
    "unknown": 0.40,
}


def score_source(source_type: str, published: str, author: str, injection_detected: bool,
                 today: date | None = None) -> float:
    today = today or date.today()
    score = TYPE_SCORES.get(source_type, TYPE_SCORES["unknown"])
    try:
        age_years = (today - date.fromisoformat(published)).days / 365.25
        if age_years > 3:
            score -= 0.15
        elif age_years > 1.5:
            score -= 0.05
    except ValueError:
        score -= 0.05  # unknown date
    if not author or author.lower() in {"guest author", "anonymous"}:
        score -= 0.05
    if injection_detected:
        score = min(score, 0.10)  # a page that tries to manipulate the agent is not evidence
    return round(max(0.0, min(1.0, score)), 2)


def quality_label(score: float) -> str:
    return "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
