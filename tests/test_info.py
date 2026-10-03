import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from config import SourcesConfig
from core.info import InfoService, format_btc, format_usd
from core.models import Article
from core.service import NewsService
from core.translate import Translator
from sources.rates import parse_cbr, parse_okx
from sources.weather import parse_gismeteo

GISMETEO = """<div class="widget-items">
<div class="widget-row widget-row-icon">
  <div class="row-item" data-tooltip="Пасмурно, небольшой дождь"></div>
  <div class="row-item" data-tooltip="Пасмурно, небольшой дождь"></div>
  <div class="row-item" data-tooltip="Облачно"></div></div>
<div class="widget-row-chart widget-row-chart-temperature-air"><div class="values">
  <div class="value"><temperature-value value="-1" from-unit="c"></temperature-value></div>
  <div class="value"><temperature-value value="4" from-unit="c"></temperature-value></div>
  <div class="value"><temperature-value value="8" from-unit="c"></temperature-value></div></div></div>
<div class="widget-row widget-row-wind">
  <div class="row-item"><div class="wind-value wind-speed"><speed-value value="2" from-unit="ms"></speed-value></div>
    <div class="wind-value wind-gust"><speed-value value="7" from-unit="ms"></speed-value></div></div>
  <div class="row-item"><div class="wind-value wind-speed"><speed-value value="5" from-unit="ms"></speed-value></div>
    <div class="wind-value wind-gust"><speed-value value="9" from-unit="ms"></speed-value></div></div></div>
<div class="widget-row widget-row-precipitation-bars">
  <div class="row-item"><div class="item-unit">0,3</div></div>
  <div class="row-item"><div class="item-unit">1,2</div></div></div></div>"""

OKX = {"code": "0", "msg": "", "data": [{"instId": "BTC-USDT", "last": "84000", "open24h": "80000"}]}
CBR = ('<?xml version="1.0" encoding="windows-1251"?><ValCurs ID="R01235">'
       '<Record Date="02.10.2026" Id="R01235"><Nominal>1</Nominal><Value>83,0000</Value></Record>'
       '<Record Date="03.10.2026" Id="R01235"><Nominal>1</Nominal><Value>83,5000</Value></Record>'
       '</ValCurs>').encode("windows-1251")
OPEN_METEO = {"daily": {"weather_code": [2, 61], "temperature_2m_max": [7.6, 7.9],
                        "temperature_2m_min": [1.1, -1.4], "precipitation_sum": [0.0, 0.0],
                        "wind_speed_10m_max": [4.5, 3.3]}}


def test_parse_gismeteo():
    f = parse_gismeteo(GISMETEO)
    assert (f.t_min, f.t_max, f.wind, f.precip) == (-1, 8, 5, 1.5)
    assert f.description == "Пасмурно, небольшой дождь"
    try:
        parse_gismeteo("<html>captcha</html>")
        raise AssertionError("ожидалась ошибка")
    except ValueError:
        pass


def test_rates_parse_and_format():
    btc = parse_okx(OKX)
    assert btc.diff == 4000 and btc.percent == 5.0
    assert "84 000.0 $" in format_btc(btc) and "▲ +5.00%" in format_btc(btc)
    usd = parse_cbr(CBR)
    assert usd.value == 83.5 and usd.previous == 83.0 and usd.as_of == "03.10.2026"
    assert "на 03.10" in format_usd(usd) and "▲ +0.50 ₽" in format_usd(usd)
    down = format_btc(parse_okx({"code": "0", "data": [{"last": "90", "open24h": "100"}]}))
    assert "▼ −10.00%" in down


def test_info_service_fallback_and_errors():
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if "open-meteo" in host:
            return httpx.Response(200, json=OPEN_METEO)
        if "okx" in host:
            return httpx.Response(200, json=OKX)
        return httpx.Response(503)  # gismeteo и ЦБ недоступны

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        info = InfoService(client, SourcesConfig().weather, "Europe/Moscow")
        return await info.weather(), await info.rates()

    weather, rates = asyncio.run(go())
    assert "Open-Meteo" in weather and "Gismeteo недоступен" in weather
    assert "Небольшой дождь" in weather and "−1…+8 °C" in weather and "без осадков" in weather
    assert "BTC/USDT" in rates and "Не удалось получить курс доллара" in rates


def test_digest_excludes_local_topic():
    now = datetime.now(timezone.utc)
    svc = NewsService(SourcesConfig(), Translator(client=httpx.AsyncClient()), httpx.AsyncClient())
    for i, topic in enumerate(["Нижний Новгород", "Мир"]):
        a = Article(title=f"Новость {topic}", url=f"https://x.ru/{i}", published=now - timedelta(hours=1),
                    source="Src", topic=topic)
        svc._store[a.url] = a
    digest = "\n".join(svc.digest_messages(now, exclude="Нижний Новгород"))
    assert "Новость Мир" in digest and "Новость Нижний Новгород" not in digest
    assert "Новость Нижний Новгород" in svc.news_messages("Нижний Новгород")[0]
