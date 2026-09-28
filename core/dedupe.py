from __future__ import annotations

from rapidfuzz import fuzz

from .models import Article
from .normalize import normalize_url


def dedupe(articles: list[Article], threshold: int = 85) -> list[Article]:
    """Убирает дубли по URL и по схожести заголовков; из дублей остаётся источник с большим весом."""
    ordered = sorted(articles, key=lambda a: (-a.weight, -a.published.timestamp()))
    kept: list[Article] = []
    urls: set[str] = set()
    for art in ordered:
        key = normalize_url(art.url)
        if key in urls:
            continue
        title = art.title.lower()
        if any(fuzz.token_set_ratio(title, k.title.lower()) >= threshold for k in kept):
            continue
        urls.add(key)
        kept.append(art)
    return kept
