"""Курсы: BTC/USDT с OKX (бывш. OKEx) и официальный курс доллара ЦБ РФ."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

OKX_TICKER = "https://www.okx.com/api/v5/market/ticker"
CBR_DYNAMIC = "https://www.cbr.ru/scripts/XML_dynamic.asp"
CBR_USD = "R01235"


@dataclass
class Rate:
    value: float
    previous: float  # значение сутки назад (для ЦБ — предыдущий установленный курс)
    as_of: str = ""

    @property
    def diff(self) -> float:
        return self.value - self.previous

    @property
    def percent(self) -> float:
        return self.diff / self.previous * 100 if self.previous else 0.0


def parse_okx(data: dict) -> Rate:
    if data.get("code") != "0" or not data.get("data"):
        raise ValueError(f"OKX: {data.get('msg') or data.get('code')}")
    t = data["data"][0]
    return Rate(float(t["last"]), float(t["open24h"]))


def parse_cbr(content: bytes | str) -> Rate:
    records = ET.fromstring(content).findall("Record")
    if len(records) < 2:
        raise ValueError("ЦБ РФ: недостаточно данных о курсе")

    def value(rec: ET.Element) -> float:
        return float(rec.findtext("Value").replace(",", ".")) / int(rec.findtext("Nominal") or 1)

    return Rate(value(records[-1]), value(records[-2]), records[-1].get("Date", ""))


async def fetch_btc(client: httpx.AsyncClient) -> Rate:
    r = await client.get(OKX_TICKER, params={"instId": "BTC-USDT"})
    r.raise_for_status()
    return parse_okx(r.json())


async def fetch_usd(client: httpx.AsyncClient, today: date) -> Rate:
    # две недели назад — с запасом на длинные выходные, когда курс не устанавливается
    r = await client.get(CBR_DYNAMIC, params={
        "date_req1": (today - timedelta(days=14)).strftime("%d/%m/%Y"),
        "date_req2": today.strftime("%d/%m/%Y"),
        "VAL_NM_RQ": CBR_USD,
    })
    r.raise_for_status()
    return parse_cbr(r.content)
