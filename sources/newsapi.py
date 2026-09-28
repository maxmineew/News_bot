from __future__ import annotations

from datetime import datetime, timezone

import httpx

from core.models import Article
from core.normalize import clean_html, normalize_url, truncate

URL = "https://newsapi.org/v2/everything"


def parse_newsapi(data: dict, src: dict) -> list[Article]:
    if data.get("status") != "ok":
        raise ValueError(f"NewsAPI: {data.get('code')} {data.get('message')}")
    articles = []
    for item in data.get("articles", []):
        if not (item.get("title") and item.get("url") and item.get("publishedAt")):
            continue
        articles.append(Article(
            title=clean_html(item["title"]),
            url=normalize_url(item["url"]),
            published=datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")).astimezone(timezone.utc),
            source=(item.get("source") or {}).get("name") or "NewsAPI",
            topic=src.get("topic", "Главное"),
            summary=truncate(clean_html(item.get("description") or "")),
            weight=float(src.get("weight", 0.8)),
        ))
    return articles


async def fetch_newsapi(client: httpx.AsyncClient, src: dict, api_key: str) -> list[Article]:
    r = await client.get(URL, params={
        "q": src["query"],
        "language": src.get("language", "ru"),
        "sortBy": "publishedAt",
        "pageSize": src.get("page_size", 30),
        "apiKey": api_key,
    })
    r.raise_for_status()
    return parse_newsapi(r.json(), src)
