"""Прогноз погоды на завтра: страница Gismeteo, запасной источник — Open-Meteo."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Gismeteo отдаёт страницу только «браузерам»
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
WMO = {
    0: "Ясно", 1: "Малооблачно", 2: "Облачно", 3: "Пасмурно", 45: "Туман", 48: "Туман, изморозь",
    51: "Слабая морось", 53: "Морось", 55: "Сильная морось", 56: "Ледяная морось", 57: "Ледяная морось",
    61: "Небольшой дождь", 63: "Дождь", 65: "Сильный дождь", 66: "Ледяной дождь", 67: "Ледяной дождь",
    71: "Небольшой снег", 73: "Снег", 75: "Сильный снег", 77: "Снежные зёрна",
    80: "Небольшой ливень", 81: "Ливень", 82: "Сильный ливень", 85: "Снегопад", 86: "Сильный снегопад",
    95: "Гроза", 96: "Гроза с градом", 99: "Гроза с градом",
}


@dataclass
class Forecast:
    description: str
    t_min: float
    t_max: float
    wind: float | None = None    # м/с, максимум за сутки
    precip: float | None = None  # мм за сутки
    source: str = "Gismeteo"
    url: str = ""


def _num(text: str) -> float:
    return float(text.strip().replace("−", "-").replace("–", "-").replace(",", ".").replace("+", ""))


def _values(soup: BeautifulSoup, row: str, tag: str, legacy: str) -> list[float]:
    """Числа из строки таблицы: новые <tag value="..."> либо старые span с текстом."""
    box = soup.select_one(row)
    if box is None:
        return []
    out = []
    for el in box.select(tag):
        try:
            out.append(_num(el.get("value") or el.get_text()))
        except ValueError:
            continue
    if not out:
        for el in box.select(legacy):
            try:
                out.append(_num(el.get_text()))
            except ValueError:
                continue
    return out


def parse_gismeteo(text: str) -> Forecast:
    soup = BeautifulSoup(text, "html.parser")
    temps = (_values(soup, ".widget-row-chart-temperature-air", "temperature-value", ".unit_temperature_c")
             or _values(soup, ".widget-row-chart-temperature", "temperature-value", ".unit_temperature_c"))
    if not temps:
        raise ValueError("на странице Gismeteo не найдена температура (изменилась вёрстка или капча)")
    tips = [el.get("data-tooltip") or el.get("data-text") or ""
            for el in soup.select(".widget-row-icon .row-item")]
    tips = [t.strip() for t in tips if t.strip()]
    # в строке ветра два числа на столбец: скорость и порывы — берём скорость
    wind = (_values(soup, ".widget-row-wind", ".wind-speed speed-value", ".wind-speed .unit_wind_m_s")
            or _values(soup, ".widget-row-wind", "speed-value", ".unit_wind_m_s"))
    precip = _values(soup, ".widget-row-precipitation-bars", ".item-unit", ".row-item")
    return Forecast(
        description=Counter(tips).most_common(1)[0][0].capitalize() if tips else "",
        t_min=min(temps), t_max=max(temps),
        wind=max(wind) if wind else None,
        precip=round(sum(precip), 1) if precip else None,
    )


def parse_open_meteo(data: dict) -> Forecast:
    d = data["daily"]  # индекс 1 — завтра
    return Forecast(
        description=WMO.get(d["weather_code"][1], ""),
        t_min=d["temperature_2m_min"][1], t_max=d["temperature_2m_max"][1],
        wind=d["wind_speed_10m_max"][1], precip=d["precipitation_sum"][1],
        source="Open-Meteo", url="https://open-meteo.com/",
    )


async def fetch_weather(client: httpx.AsyncClient, cfg: dict) -> Forecast:
    # gismeteo.ru отвечает 403 зарубежным адресам и VPN — тогда то же самое с зеркала gismeteo.by
    main = cfg["gismeteo_url"]
    for url in dict.fromkeys([main, main.replace("gismeteo.ru", "gismeteo.by")]):
        try:
            r = await client.get(url, headers=BROWSER_HEADERS)
            r.raise_for_status()
            forecast = parse_gismeteo(r.text)
            forecast.url = url
            return forecast
        except Exception as exc:  # noqa: BLE001 — Gismeteo недоступен: берём запасной источник
            log.warning("gismeteo %s: %s: %s", url, type(exc).__name__, exc)
    r = await client.get(OPEN_METEO, params={
        "latitude": cfg["lat"], "longitude": cfg["lon"], "forecast_days": 2,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "wind_speed_unit": "ms", "timezone": cfg.get("tz", "Europe/Moscow"),
    })
    r.raise_for_status()
    return parse_open_meteo(r.json())
