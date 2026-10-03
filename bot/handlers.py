from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, TelegramObject

from config import Settings
from core.info import InfoService
from core.service import NewsService

from .scheduler import NewsScheduler, parse_hhmm

HELP = (
    "<b>Новостной бот</b>\n"
    "/news [тема] — свежие новости (10 шт.)\n"
    "/topics — рубрики и источники\n"
    "/digest — дайджест прямо сейчас\n"
    "/weather — погода на завтра · /btc — BTC/USDT · /usd — курс доллара\n"
    "/sources — состояние источников\n"
    "/time ЧЧ:ММ — время утренней сводки (только владелец)\n\n"
    "Утром приходят курсы, новости города и дайджест, вечером — погода на завтра.\n"
    "Новости на иностранных языках автоматически переводятся на русский."
)

BTN_WEATHER, BTN_BTC, BTN_USD = "🌤 Погода", "₿ BTC", "💵 Доллар"
BTN_WORLD, BTN_RUSSIA, BTN_LOCAL = "🌍 Мир", "🇷🇺 Россия", "🏙 Нижний Новгород"
NEWS_BUTTONS = {BTN_WORLD: "Мир", BTN_RUSSIA: "Россия"}
KEYBOARD = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=BTN_WEATHER), KeyboardButton(text=BTN_BTC), KeyboardButton(text=BTN_USD)],
    [KeyboardButton(text=BTN_WORLD), KeyboardButton(text=BTN_RUSSIA), KeyboardButton(text=BTN_LOCAL)],
])


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


def build_router(service: NewsService, info: InfoService, settings: Settings,
                 sched: NewsScheduler) -> Router:
    router = Router()
    router.message.outer_middleware(AllowlistMiddleware(settings.allowed_ids))
    tz = ZoneInfo(settings.tz)

    async def reply_all(message: Message, texts: list[str]) -> None:
        for t in texts:
            await message.answer(t)

    @router.message(Command("start", "help"))
    async def start(message: Message) -> None:
        await message.answer(HELP, reply_markup=KEYBOARD)

    @router.message(Command("weather"))
    @router.message(F.text == BTN_WEATHER)
    async def weather(message: Message) -> None:
        await message.answer(await info.weather())

    @router.message(Command("btc"))
    @router.message(F.text == BTN_BTC)
    async def btc(message: Message) -> None:
        await message.answer(await info.btc())

    @router.message(Command("usd"))
    @router.message(F.text == BTN_USD)
    async def usd(message: Message) -> None:
        await message.answer(await info.usd())

    @router.message(F.text.in_({BTN_WORLD, BTN_RUSSIA, BTN_LOCAL}))
    async def news_button(message: Message) -> None:
        topic = NEWS_BUTTONS.get(message.text, service.cfg.local_topic)
        await reply_all(message, service.news_messages(topic))

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
