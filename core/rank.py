from __future__ import annotations

from datetime import datetime

from .models import Article


def is_blocked(article: Article, stopwords: list[str]) -> bool:
    text = f"{article.title} {article.summary}".lower()
    return any(w.lower() in text for w in stopwords)


def score(article: Article, now: datetime, keywords: list[str], max_age_hours: int) -> float:
    age_h = max((now - article.published).total_seconds() / 3600, 0)
    freshness = max(0.0, 1 - age_h / max_age_hours)
    text = f"{article.title} {article.summary}".lower()
    hits = sum(1 for k in keywords if k.lower() in text)
    return freshness + article.weight + 0.5 * min(hits, 3)


def rank(
    articles: list[Article],
    now: datetime,
    keywords: list[str],
    stopwords: list[str],
    max_age_hours: int,
) -> list[Article]:
    fresh = [
        a for a in articles
        if 0 <= (now - a.published).total_seconds() <= max_age_hours * 3600 and not is_blocked(a, stopwords)
    ]
    return sorted(fresh, key=lambda a: score(a, now, keywords, max_age_hours), reverse=True)
