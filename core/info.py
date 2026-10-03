"""Погода и курсы: получение и готовый текст для Telegram. Сбой источника — текст об ошибке."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from sources.rates import Rate, fetch_btc, fetch_usd
from sources.weather import Forecast, fetch_weather

from .digest import _MONTHS

log = logging.getLogger(__name__)


def _signed(value: float, digits: int = 2) -> str:
    return f"{value:+,.{digits}f}".replace(",", " ").replace("-", "−")


def _arrow(value: float) -> str:
    return "▲" if value > 0 else "▼" if value < 0 else "•"


def format_btc(rate: Rate) -> str:
    price = f"{rate.value:,.1f}".replace(",", " ")
    return (f"₿ <b>BTC/USDT</b> (OKX): {price} $\n"
            f"За сутки: {_arrow(rate.diff)} {_signed(rate.percent)}% ({_signed(rate.diff, 1)} $)")


def format_usd(rate: Rate) -> str:
    as_of = f" на {rate.as_of[:5]}" if rate.as_of else ""
    return (f"💵 <b>USD/RUB</b> (ЦБ РФ{as_of}): {rate.value:.2f} ₽\n"
            f"За сутки: {_arrow(rate.diff)} {_signed(rate.diff)} ₽ ({_signed(rate.percent)}%)")


def format_weather(f: Forecast, city: str, day: datetime) -> str:
    lines = [f"🌤 <b>Погода: {html.escape(city)}, завтра, {day.day} {_MONTHS[day.month - 1]}</b>"]
    if f.description:
        lines.append(html.escape(f.description))
    lines.append(f"🌡 {_signed(f.t_min, 0)}…{_signed(f.t_max, 0)} °C")
    if f.wind is not None:
        lines.append(f"💨 ветер до {f.wind:.0f} м/с")
    if f.precip is not None:
        lines.append(f"☔ осадки {f.precip:g} мм" if f.precip else "☔ без осадков")
    note = "" if f.source == "Gismeteo" else " (Gismeteo недоступен)"
    lines.append(f'Источник: <a href="{html.escape(f.url, quote=True)}">{f.source}</a>{note}')
    return "\n".join(lines)


class InfoService:
    def __init__(self, client: httpx.AsyncClient, weather_cfg: dict, tz: str) -> None:
        self.client = client
        self.weather_cfg = {**weather_cfg, "tz": tz}
        self.tz = ZoneInfo(tz)

    async def _safe(self, what: str, make) -> str:
        try:
            return await make()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: %s: %s", what, type(exc).__name__, exc)
            return f"⚠️ Не удалось получить {what}: {html.escape(type(exc).__name__)}"

    async def weather(self) -> str:
        async def make() -> str:
            forecast = await fetch_weather(self.client, self.weather_cfg)
            tomorrow = datetime.now(self.tz) + timedelta(days=1)
            return format_weather(forecast, self.weather_cfg["city"], tomorrow)
        return await self._safe("погоду", make)

    async def btc(self) -> str:
        async def make() -> str:
            return format_btc(await fetch_btc(self.client))
        return await self._safe("курс BTC", make)

    async def usd(self) -> str:
        async def make() -> str:
            return format_usd(await fetch_usd(self.client, datetime.now(self.tz).date()))
        return await self._safe("курс доллара", make)

    async def rates(self) -> str:
        return f"{await self.btc()}\n\n{await self.usd()}"
