"""Встроенный планировщик: периодический сбор + утренний дайджест владельцу."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Settings
from core.service import NewsService, RefreshReport

log = logging.getLogger(__name__)
ALERT_INTERVAL = 3600  # предупреждения владельцу — не чаще 1/час


def parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(value)
    return h, m


class NewsScheduler:
    def __init__(self, bot: Bot, service: NewsService, settings: Settings) -> None:
        self.bot, self.service, self.settings = bot, service, settings
        self.tz = ZoneInfo(settings.tz)
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self.digest_time = settings.digest_time
        self._last_alert = 0.0

    def start(self) -> None:
        self.scheduler.add_job(self.refresh, "interval", minutes=self.settings.refresh_minutes,
                               id="refresh", max_instances=1, coalesce=True)
        self.set_digest_time(self.digest_time)
        self.scheduler.start()

    def set_digest_time(self, value: str) -> None:
        h, m = parse_hhmm(value)
        self.scheduler.add_job(self.send_digest, "cron", hour=h, minute=m, id="digest",
                               replace_existing=True, misfire_grace_time=3600, coalesce=True)
        self.digest_time = f"{h:02d}:{m:02d}"

    async def refresh(self) -> RefreshReport:
        report = await self.service.refresh()
        await self._alert(report)
        return report

    async def send_digest(self) -> None:
        await self.refresh()
        now = datetime.now(self.tz)
        for text in self.service.digest_messages(now):
            await self.bot.send_message(self.settings.owner_id, text)

    async def _alert(self, report: RefreshReport) -> None:
        problems = []
        if report.failed_sources:
            problems.append("Не отвечают источники: " + ", ".join(report.failed_sources))
        if report.untranslated:
            problems.append(f"Не переведено новостей: {report.untranslated}")
        if not problems or time.monotonic() - self._last_alert < ALERT_INTERVAL:
            return
        self._last_alert = time.monotonic()
        try:
            await self.bot.send_message(self.settings.owner_id, "⚠️ " + "\n".join(problems),
                                        parse_mode=None)
        except Exception:  # noqa: BLE001
            log.exception("не удалось отправить предупреждение владельцу")
