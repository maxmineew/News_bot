import asyncio

import httpx

from core.translate import Translator, _split, is_russian


def run(coro):
    return asyncio.run(coro)


def test_is_russian():
    assert is_russian("Привет, мир")
    assert is_russian("2026 🚀")
    assert not is_russian("OpenAI launches a new model")


def test_split_respects_limit():
    text = ("Sentence number one is here. " * 400).strip()
    parts = _split(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert " ".join(parts).split() == text.split()


def _mock(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_translate_uses_primary_and_cache():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=[[["Привет", "Hello", None]], None, "en"])

    async def go():
        tr = Translator(client=_mock(handler))
        a = await tr.translate("Hello")
        b = await tr.translate("Hello")  # из кэша
        await tr.aclose()
        return a, b

    a, b = run(go())
    assert a.text == "Привет" and a.translated
    assert b.text == "Привет" and len(calls) == 1


def test_fallback_when_primary_fails():
    def handler(req: httpx.Request) -> httpx.Response:
        if "translate.googleapis.com" in str(req.url):
            return httpx.Response(429)
        return httpx.Response(200, json=[["Привет", "en"]])

    async def go():
        tr = Translator(client=_mock(handler))
        r = await tr.translate("Hello")
        await tr.aclose()
        return r

    r = run(go())
    assert r.text == "Привет" and r.translated


def test_returns_original_when_all_fail():
    async def go():
        tr = Translator(client=_mock(lambda req: httpx.Response(500)))
        r = await tr.translate("Hello")
        await tr.aclose()
        return r

    r = run(go())
    assert r.text == "Hello" and not r.translated


def test_russian_not_translated_and_daily_limit():
    def handler(req):
        raise AssertionError("не должно быть сетевых вызовов")

    async def go():
        tr = Translator(daily_chars=3, client=_mock(handler))
        ru = await tr.translate("Уже по-русски")
        over = await tr.translate("Hello world")  # превышает лимит 3
        await tr.aclose()
        return ru, over

    ru, over = run(go())
    assert not ru.translated and ru.text == "Уже по-русски"
    assert not over.translated and over.text == "Hello world"


def test_429_puts_endpoint_on_cooldown():
    hits = {"primary": 0, "fallback": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if "translate.googleapis.com" in str(req.url):
            hits["primary"] += 1
            return httpx.Response(429)
        hits["fallback"] += 1
        return httpx.Response(200, json=[["Привет", "en"]])

    async def go():
        tr = Translator(client=_mock(handler))
        for word in ("Hello", "World", "Again"):
            assert (await tr.translate(word)).translated
        await tr.aclose()

    run(go())
    assert hits["primary"] == 1  # после первого 429 основной больше не трогаем
    assert hits["fallback"] == 3
