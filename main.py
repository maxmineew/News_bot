from __future__ import annotations

import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import build_router
from bot.scheduler import NewsScheduler
from config import Settings, SourcesConfig
from core.service import NewsService
from core.translate import Translator

UA = "Mozilla/5.0 (compatible; NewsBot/1.0)"
log = logging.getLogger("startup")

PROBES = {
    "telegram": "https://api.telegram.org",
    "google-translate": "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t&q=hello",
    "techcrunch-rss": "https://techcrunch.com/feed/",
    "t.me": "https://t.me/s/telegram",
}


async def probe_network(client: httpx.AsyncClient) -> None:
    """Этап 0 ТЗ: одна строка на каждый внешний хост — видно в логах панели хостинга."""
    async def one(name: str, url: str) -> str:
        try:
            r = await client.get(url, timeout=8)
            return f"{name}=HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            return f"{name}=FAIL {type(exc).__name__}"

    log.info("network probe: %s", "; ".join(await asyncio.gather(*(one(n, u) for n, u in PROBES.items()))))


async def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = SourcesConfig.load()

    client = httpx.AsyncClient(timeout=10, follow_redirects=True, headers={"User-Agent": UA})
    translator = Translator(daily_chars=settings.translate_daily_chars)
    service = NewsService(cfg, translator, client, settings.newsapi_key)

    bot = Bot(settings.token, default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    sched = NewsScheduler(bot, service, settings)
    dp = Dispatcher()
    dp.include_router(build_router(service, settings, sched))

    asyncio.create_task(probe_network(client))
    sched.start()
    first_refresh = asyncio.create_task(sched.refresh())  # не блокируем старт polling
    try:
        await dp.start_polling(bot)
    finally:
        first_refresh.cancel()
        sched.scheduler.shutdown(wait=False)
        await translator.aclose()
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
