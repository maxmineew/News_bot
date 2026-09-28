from __future__ import annotations

import html
from datetime import datetime

from .models import Article

MESSAGE_LIMIT = 3500  # запас до лимита Telegram (4096)
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]


def format_item(a: Article) -> str:
    mark = " (EN)" if a.translated else " [не переведено]" if a.foreign else ""
    title = html.escape(a.title)
    url = html.escape(a.url, quote=True)
    return f'• <a href="{url}">{title}</a> — {html.escape(a.source)}{mark}'


def _split_block(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    out, buf = [], ""
    for line in block.split("\n"):
        if buf and len(buf) + len(line) + 1 > limit:
            out.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out


def pack(blocks: list[str], limit: int = MESSAGE_LIMIT) -> list[str]:
    """Собирает блоки в сообщения ≤ limit символов, не разрывая блок без необходимости."""
    messages, buf = [], ""
    for block in blocks:
        for part in _split_block(block, limit):
            if buf and len(buf) + len(part) + 2 > limit:
                messages.append(buf)
                buf = part
            else:
                buf = f"{buf}\n\n{part}" if buf else part
    if buf:
        messages.append(buf)
    return messages


def build_digest(ranked: list[Article], now: datetime, per_topic: int = 5) -> list[str]:
    title = f"📰 <b>Дайджест на {now.day} {_MONTHS[now.month - 1]} {now.year}</b>"
    if not ranked:
        return [f"{title}\n\nСвежих новостей пока нет."]
    topics: dict[str, list[Article]] = {}
    for a in ranked:  # порядок рубрик — по лучшей новости в рубрике
        topics.setdefault(a.topic, [])
        if len(topics[a.topic]) < per_topic:
            topics[a.topic].append(a)
    blocks = [title] + [
        f"<b>{html.escape(topic)}</b>\n" + "\n".join(format_item(a) for a in items)
        for topic, items in topics.items()
    ]
    return pack(blocks)


def build_list(ranked: list[Article], header: str) -> list[str]:
    if not ranked:
        return [f"{html.escape(header)}\n\nНичего не найдено."]
    return pack([f"<b>{html.escape(header)}</b>\n" + "\n".join(format_item(a) for a in ranked)])
