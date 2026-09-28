from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import httpx

from core.models import Article
from core.normalize import clean_html, normalize_url, truncate


def parse_rss(text: str, src: dict) -> list[Article]:
    feed = feedparser.parse(text)
    if feed.bozo and not feed.entries:
        raise ValueError(f"не удалось разобрать ленту: {feed.bozo_exception}")
    articles = []
    for e in feed.entries:
        struct = e.get("published_parsed") or e.get("updated_parsed")
        if not struct or not e.get("link") or not e.get("title"):
            continue
        articles.append(Article(
            title=clean_html(e.title),
            url=normalize_url(e.link),
            published=datetime(*struct[:6], tzinfo=timezone.utc),
            source=src["name"],
            topic=src.get("topic", "Главное"),
            summary=truncate(clean_html(e.get("summary", ""))),
            weight=float(src.get("weight", 1.0)),
        ))
    return articles


async def fetch_rss(client: httpx.AsyncClient, src: dict) -> list[Article]:
    r = await client.get(src["url"])
    r.raise_for_status()
    return parse_rss(r.text, src)
