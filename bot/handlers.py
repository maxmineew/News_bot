from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, TelegramObject

from config import Settings
from core.service import NewsService

from .scheduler import NewsScheduler, parse_hhmm

HELP = (
    "<b>Новостной бот</b>\n"
    "/news [тема] — свежие новости (10 шт.)\n"
    "/topics — рубрики и источники\n"
    "/digest — дайджест прямо сейчас\n"
    "/sources — состояние источников\n"
    "/time ЧЧ:ММ — время утреннего дайджеста (только владелец)\n\n"
    "Новости на иностранных языках автоматически переводятся на русский."
)


class AllowlistMiddleware(BaseMiddleware):
    """Чужим пользователям не отвечаем вообще."""

    def __init__(self, allowed: set[int]) -> None:
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self.allowed:
            return None
        return await handler(event, data)


def build_router(service: NewsService, settings: Settings, sched: NewsScheduler) -> Router:
    router = Router()
    router.message.outer_middleware(AllowlistMiddleware(settings.allowed_ids))
    tz = ZoneInfo(settings.tz)

    async def reply_all(message: Message, texts: list[str]) -> None:
        for t in texts:
            await message.answer(t)

    @router.message(Command("start", "help"))
    async def start(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("news"))
    async def news(message: Message, command: CommandObject) -> None:
        topic = (command.args or "").strip() or None
        await reply_all(message, service.news_messages(topic))

    @router.message(Command("topics"))
    async def topics(message: Message) -> None:
        lines = [f"<b>{html.escape(t)}</b>: {html.escape(', '.join(src))}"
                 for t, src in service.topics().items()]
        await message.answer("\n".join(lines) or "Источники не настроены.")

    @router.message(Command("digest"))
    async def digest(message: Message) -> None:
        await sched.refresh()
        await reply_all(message, service.digest_messages(datetime.now(tz)))

    @router.message(Command("sources"))
    async def sources(message: Message) -> None:
        if not service.status:
            await message.answer("Сбор ещё не выполнялся.")
            return
        lines = []
        for st in service.status.values():
            if st.last_error:
                lines.append(f"❌ {html.escape(st.name)} — {html.escape(st.last_error)}")
            else:
                ts = st.last_ok.astimezone(tz).strftime("%H:%M") if st.last_ok else "—"
                lines.append(f"✅ {html.escape(st.name)} — {st.count} шт., {ts}")
        await message.answer("\n".join(lines))

    @router.message(Command("time"))
    async def set_time(message: Message, command: CommandObject) -> None:
        if message.from_user.id != settings.owner_id:
            await message.answer("Менять время может только владелец.")
            return
        try:
            h, m = parse_hhmm(command.args or "")
        except ValueError:
            await message.answer(f"Формат: /time ЧЧ:ММ. Сейчас дайджест в {sched.digest_time} ({settings.tz}).")
            return
        sched.set_digest_time(f"{h}:{m}")
        await message.answer(f"Дайджест теперь в {sched.digest_time} ({settings.tz}).")

    return router
