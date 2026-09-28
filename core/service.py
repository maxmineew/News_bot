"""Сбор новостей из всех источников, перевод, дедупликация, хранение в памяти."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from config import SourcesConfig
from sources.newsapi import fetch_newsapi
from sources.rss import fetch_rss
from sources.tgchannel import fetch_channel

from .dedupe import dedupe
from .digest import build_digest, build_list
from .models import Article
from .rank import rank
from .translate import Translator, is_russian

log = logging.getLogger(__name__)


@dataclass
class SourceStatus:
    kind: str
    name: str
    last_ok: datetime | None = None
    last_error: str = ""
    count: int = 0


@dataclass
class RefreshReport:
    failed_sources: list[str] = field(default_factory=list)
    untranslated: int = 0
    new_articles: int = 0


class NewsService:
    def __init__(
        self,
        cfg: SourcesConfig,
        translator: Translator,
        client: httpx.AsyncClient,
        newsapi_key: str = "",
    ) -> None:
        self.cfg = cfg
        self.translator = translator
        self.client = client
        self.newsapi_key = newsapi_key
        self.status: dict[str, SourceStatus] = {}
        self._store: dict[str, Article] = {}
        self._lock = asyncio.Lock()
        self._newsapi_day = date.min
        self._newsapi_used = 0

    # -- источники ---------------------------------------------------------
    def _jobs(self) -> list[tuple[str, str, object]]:
        jobs = [("rss", s["name"], lambda s=s: fetch_rss(self.client, s)) for s in self.cfg.rss]
        jobs += [
            ("tg", f"@{s['channel']}", lambda s=s: fetch_channel(self.client, s))
            for s in self.cfg.telegram
        ]
        if self.newsapi_key:
            for s in self.cfg.newsapi.get("queries", []):
                jobs.append(("newsapi", s["query"], lambda s=s: self._fetch_newsapi(s)))
        return jobs

    async def _fetch_newsapi(self, src: dict) -> list[Article]:
        today = date.today()
        if today != self._newsapi_day:
            self._newsapi_day, self._newsapi_used = today, 0
        if self._newsapi_used >= self.cfg.newsapi.get("max_requests_per_day", 20):
            raise RuntimeError("суточный лимит запросов NewsAPI исчерпан")
        self._newsapi_used += 1
        return await fetch_newsapi(self.client, src, self.newsapi_key)

    async def _run_job(self, kind: str, name: str, factory) -> list[Article]:
        st = self.status.setdefault(f"{kind}:{name}", SourceStatus(kind, name))
        try:
            articles = await factory()
        except Exception as exc:  # noqa: BLE001 — сбой одного источника не ломает сбор
            st.last_error = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("источник %s/%s: %s", kind, name, st.last_error)
            return []
        st.last_ok, st.last_error, st.count = datetime.now(timezone.utc), "", len(articles)
        return articles

    # -- сбор --------------------------------------------------------------
    async def refresh(self) -> RefreshReport:
        async with self._lock:
            now = datetime.now(timezone.utc)
            retention = timedelta(hours=self.cfg.max_age_hours * 2)
            results = await asyncio.gather(*(self._run_job(k, n, f) for k, n, f in self._jobs()))
            fetched = [a for chunk in results for a in chunk if now - a.published <= retention]

            new = [a for a in fetched if a.url not in self._store]
            for a in new:
                a.foreign = not is_russian(a.title)
            # перевод — сразу при поступлении, до дедупликации; плюс повтор для ранее неудавшихся
            to_translate = new + [a for a in self._store.values() if a.foreign and not a.translated]
            await self._translate(to_translate)

            merged = list(self._store.values()) + new
            merged = [a for a in merged if now - a.published <= retention]
            kept = dedupe(merged)
            kept.sort(key=lambda a: a.published, reverse=True)
            self._store = {a.url: a for a in kept[: self.cfg.max_articles]}

            failed = [f"{s.kind}:{s.name}" for s in self.status.values() if s.last_error]
            untranslated = sum(1 for a in self._store.values() if a.foreign and not a.translated)
            log.info("refresh: +%d новых, в памяти %d, ошибок %d", len(new), len(self._store), len(failed))
            return RefreshReport(failed, untranslated, len(new))

    async def _translate(self, articles: list[Article]) -> None:
        if not articles:
            return
        titles = await self.translator.translate_many([a.title for a in articles])
        summaries = await self.translator.translate_many([a.summary for a in articles])
        for a, t, s in zip(articles, titles, summaries):
            if t.translated:
                a.title, a.translated = t.text, True
                if s.translated:
                    a.summary = s.text

    # -- выдача ------------------------------------------------------------
    def topics(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for s in self.cfg.rss:
            result.setdefault(s.get("topic", "Главное"), []).append(s["name"])
        for s in self.cfg.telegram:
            result.setdefault(s.get("topic", "Главное"), []).append(f"@{s['channel']}")
        for s in self.cfg.newsapi.get("queries", []):
            result.setdefault(s.get("topic", "Главное"), []).append(f"NewsAPI: {s['query']}")
        return result

    def ranked(self, topic: str | None = None) -> list[Article]:
        now = datetime.now(timezone.utc)
        items = rank(list(self._store.values()), now, self.cfg.keywords, self.cfg.stopwords,
                     self.cfg.max_age_hours)
        if topic:
            items = [a for a in items if a.topic.lower() == topic.lower()]
        return items

    def digest_messages(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        return build_digest(self.ranked(), now, self.cfg.per_topic)

    def news_messages(self, topic: str | None = None, limit: int = 10) -> list[str]:
        header = f"Новости: {topic}" if topic else "Свежие новости"
        return build_list(self.ranked(topic)[:limit], header)
