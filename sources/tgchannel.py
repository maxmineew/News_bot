"""Парсинг публичных Telegram-каналов через веб-версию https://t.me/s/<channel>.

Хрупко: зависит от разметки t.me. Если разметка изменилась и постов не найдено,
бросаем ошибку — сервис пометит источник неисправным, остальные продолжат работать.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from core.models import Article
from core.normalize import normalize_url, truncate


def parse_channel(html_text: str, src: dict) -> list[Article]:
    soup = BeautifulSoup(html_text, "html.parser")
    posts = soup.select(".tgme_widget_message_wrap")
    if not posts:
        raise ValueError("посты не найдены (разметка t.me изменилась или канал закрыт)")
    articles = []
    for post in posts:
        text_el = post.select_one(".tgme_widget_message_text")
        date_el = post.select_one("a.tgme_widget_message_date")
        time_el = post.select_one("time")
        if not (text_el and date_el and time_el and time_el.get("datetime")):
            continue
        text = text_el.get_text("\n", strip=True)
        first = text.split("\n", 1)[0]
        articles.append(Article(
            title=truncate(first, 140),
            url=normalize_url(date_el["href"]),
            published=datetime.fromisoformat(time_el["datetime"]).astimezone(timezone.utc),
            source=src.get("name") or f"@{src['channel']}",
            topic=src.get("topic", "Главное"),
            summary=truncate(text, 200),
            weight=float(src.get("weight", 1.0)),
        ))
    return articles


async def fetch_channel(client: httpx.AsyncClient, src: dict) -> list[Article]:
    r = await client.get(f"https://t.me/s/{src['channel']}")
    r.raise_for_status()
    return parse_channel(r.text, src)
