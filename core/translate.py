"""Бесплатный перевод на русский через публичные эндпоинты Google Translate (без ключа).

Основной эндпоинт: translate.googleapis.com (client=gtx).
Запасной: clients5.google.com (client=dict-chrome-ex).
Оба неофициальные: без SLA, могут отдать 429/блокировку -> при полной неудаче
возвращаем оригинал и помечаем translated=False, бот не падает.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

PRIMARY_URL = "https://translate.googleapis.com/translate_a/single"
FALLBACK_URL = "https://clients5.google.com/translate_a/t"
COOLDOWN = 300  # секунд паузы эндпоинта после 429
MAX_CHUNK = 4500  # безопасный размер одного запроса (символов)
_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_LETTER = re.compile(r"[^\W\d_]")


@dataclass
class Result:
    text: str
    translated: bool


def is_russian(text: str, threshold: float = 0.5) -> bool:
    """Текст считается русским, если >=50% его букв — кириллица."""
    letters = _LETTER.findall(text)
    if not letters:
        return True  # нечего переводить (цифры, эмодзи)
    return len(_CYRILLIC.findall(text)) / len(letters) >= threshold


def _split(text: str, limit: int = MAX_CHUNK) -> list[str]:
    """Режем длинный текст по границам предложений/пробелов."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit:  # предложение длиннее лимита
            cut = sentence.rfind(" ", 0, limit) or limit
            if cut <= 0:
                cut = limit
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if len(buf) + len(sentence) + 1 > limit and buf:
            parts.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        parts.append(buf)
    return parts


class Translator:
    def __init__(
        self,
        target: str = "ru",
        daily_chars: int = 200_000,
        cache_size: int = 2000,
        concurrency: int = 4,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.target = target
        self.daily_chars = daily_chars
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_size = cache_size
        self._sem = asyncio.Semaphore(concurrency)
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._used = 0
        self._day = ""
        self._blocked_until: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- публичный API ---------------------------------------------------
    async def translate(self, text: str) -> Result:
        text = (text or "").strip()
        if not text or is_russian(text):
            return Result(text, False)
        if text in self._cache:
            self._cache.move_to_end(text)
            return Result(self._cache[text], True)
        if not self._reserve(len(text)):
            log.warning("translate: суточный лимит символов исчерпан")
            return Result(text, False)
        try:
            chunks = _split(text)
            out = [await self._translate_chunk(c) for c in chunks]
        except Exception as exc:  # noqa: BLE001 — любая сетевая ошибка не должна ронять бота
            log.warning("translate: не удалось перевести (%s)", exc)
            return Result(text, False)
        result = " ".join(out)
        self._remember(text, result)
        return Result(result, True)

    async def translate_many(self, texts: list[str]) -> list[Result]:
        return list(await asyncio.gather(*(self.translate(t) for t in texts)))

    # -- внутреннее ------------------------------------------------------
    def _reserve(self, n: int) -> bool:
        import datetime as _dt

        today = _dt.date.today().isoformat()
        if today != self._day:
            self._day, self._used = today, 0
        if self._used + n > self.daily_chars:
            return False
        self._used += n
        return True

    def _remember(self, key: str, value: str) -> None:
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def _translate_chunk(self, chunk: str) -> str:
        async with self._sem:
            last: Exception | None = None
            for name, fn in (("primary", self._primary), ("fallback", self._fallback)):
                if time.monotonic() < self._blocked_until.get(name, 0.0):
                    continue  # эндпоинт недавно отдал 429 — не долбим его
                for _ in range(2):  # 1 повтор на эндпоинт
                    try:
                        return await fn(chunk)
                    except httpx.HTTPStatusError as exc:
                        last = exc
                        if exc.response.status_code == 429:
                            self._blocked_until[name] = time.monotonic() + COOLDOWN
                            log.warning("translate: %s вернул 429, пауза %d с", name, COOLDOWN)
                            break  # повторять бессмысленно
                        await asyncio.sleep(0.5)
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        await asyncio.sleep(0.5)
            raise RuntimeError(f"Google Translate недоступен: {last}")

    async def _primary(self, chunk: str) -> str:
        r = await self._client.post(
            PRIMARY_URL,
            params={"client": "gtx", "sl": "auto", "tl": self.target, "dt": "t"},
            data={"q": chunk},
        )
        r.raise_for_status()
        return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])

    async def _fallback(self, chunk: str) -> str:
        r = await self._client.post(
            FALLBACK_URL,
            params={"client": "dict-chrome-ex", "sl": "auto", "tl": self.target},
            data={"q": chunk},
        )
        r.raise_for_status()
        data = r.json()
        first = data[0]
        return first[0] if isinstance(first, list) else first


if __name__ == "__main__":  # ручная проверка: python -m core.translate "Some English text"
    import sys

    async def _main() -> None:
        tr = Translator()
        try:
            res = await tr.translate(" ".join(sys.argv[1:]) or "OpenAI launches a new model for developers")
            print(res)
        finally:
            await tr.aclose()

    asyncio.run(_main())
