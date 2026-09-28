import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from config import SourcesConfig
from core.dedupe import dedupe
from core.digest import MESSAGE_LIMIT, build_digest, format_item, pack
from core.models import Article
from core.normalize import clean_html, normalize_url, truncate
from core.rank import rank
from core.service import NewsService
from core.translate import Translator
from sources.rss import parse_rss
from sources.tgchannel import parse_channel

NOW = datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)


def art(title="Заголовок", url="https://x.ru/1", hours=1, weight=1.0, topic="Главное", **kw):
    return Article(title=title, url=url, published=NOW - timedelta(hours=hours),
                   source="Src", topic=topic, weight=weight, **kw)


def test_normalize():
    assert normalize_url("https://Site.com/a/?utm_source=x&id=5#frag") == "https://site.com/a?id=5"
    assert clean_html("<p>Hi&nbsp;&amp; <b>bye</b></p>") == "Hi & bye"
    assert truncate("слово " * 100, 50).endswith("…")


def test_dedupe_by_url_and_title_prefers_weight():
    a = art("Apple выпустила новый iPhone", "https://a.ru/1", weight=1.0)
    b = art("Apple выпустила новый iPhone!", "https://b.ru/2", weight=1.5)
    c = art("Совсем другая новость", "https://c.ru/3")
    d = art("Совсем другая новость", "https://c.ru/3?utm_medium=z")
    kept = dedupe([a, b, c, d])
    assert len(kept) == 2 and b in kept and a not in kept


def test_rank_filters_old_and_stopwords():
    fresh = art("Про ИИ", "https://x/1", hours=1)
    old = art("Старое", "https://x/2", hours=30)
    spam = art("Реклама казино", "https://x/3", hours=1)
    res = rank([fresh, old, spam], NOW, keywords=["ии"], stopwords=["казино"], max_age_hours=24)
    assert res == [fresh]


def test_digest_format_marks_and_escape():
    tr = art("A <b> & B", "https://x/?a=1&b=2", foreign=True, translated=True)
    assert "&lt;b&gt;" in format_item(tr) and "(EN)" in format_item(tr)
    assert "[не переведено]" in format_item(art(foreign=True))


def test_digest_split_and_empty():
    items = [art(f"Новость номер {i} " * 5, f"https://x/{i}", topic="Т") for i in range(120)]
    msgs = build_digest(items, NOW, per_topic=120)
    assert len(msgs) > 1 and all(len(m) <= MESSAGE_LIMIT for m in msgs)
    assert "Свежих новостей пока нет" in build_digest([], NOW)[0]
    assert "28 сентября 2026" in build_digest([], NOW)[0]
    assert pack(["a" * 10, "b" * 10], limit=15) == ["a" * 10, "b" * 10]


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>TechCrunch story</title><link>https://tc.com/a?utm_source=x</link>
<pubDate>Mon, 28 Sep 2026 06:00:00 +0000</pubDate><description>&lt;p&gt;Body text&lt;/p&gt;</description></item>
<item><title>No date</title><link>https://tc.com/b</link></item></channel></rss>"""


def test_parse_rss():
    res = parse_rss(RSS, {"name": "TC", "topic": "Технологии", "weight": 1.2})
    assert len(res) == 1
    a = res[0]
    assert a.url == "https://tc.com/a" and a.summary == "Body text" and a.weight == 1.2
    assert a.published == datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


TG = """<div class="tgme_widget_message_wrap"><div class="tgme_widget_message_text">Заголовок поста<br>Подробности</div>
<a class="tgme_widget_message_date" href="https://t.me/chan/5"><time datetime="2026-09-28T09:00:00+03:00"></time></a></div>"""


def test_parse_channel():
    res = parse_channel(TG, {"channel": "chan", "topic": "Главное"})
    assert res[0].title == "Заголовок поста" and res[0].url == "https://t.me/chan/5"
    assert res[0].published == datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
    try:
        parse_channel("<html></html>", {"channel": "chan"})
        raise AssertionError("ожидалась ошибка")
    except ValueError:
        pass


def test_service_refresh_translates_and_survives_broken_source():
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    feed = RSS.replace("Mon, 28 Sep 2026 06:00:00 +0000", recent)

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "translate" in url:
            return httpx.Response(200, json=[[["История TechCrunch", "x", None]], None, "en"])
        if "good.test" in url:
            return httpx.Response(200, text=feed)
        return httpx.Response(500)

    cfg = SourcesConfig(rss=[
        {"name": "TC", "url": "https://good.test/feed", "topic": "Технологии"},
        {"name": "Broken", "url": "https://bad.test/feed", "topic": "Главное"},
    ])

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        tr = Translator(client=client)
        svc = NewsService(cfg, tr, client)
        report = await svc.refresh()
        return svc, report

    svc, report = asyncio.run(go())
    assert report.failed_sources == ["rss:Broken"] and report.new_articles == 1
    top = svc.ranked()
    assert top[0].title == "История TechCrunch" and top[0].translated
    assert "Технологии" in svc.topics()
    assert "(EN)" in svc.digest_messages()[0]


def test_dotenv_inline_comments_and_quotes():
    from config import _clean_value
    assert _clean_value("12345   # ваш ID") == "12345"
    assert _clean_value("   # только комментарий") == ""
    assert _clean_value('"a # b"') == "a # b"
    assert _clean_value("tok:en_123") == "tok:en_123"


def test_settings_fallback_to_sources_yaml(tmp_path, monkeypatch):
    from config import Settings
    for k in ("TELEGRAM_BOT_TOKEN", "OWNER_ID", "ALLOWED_USER_IDS", "DIGEST_TIME", "TZ"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("BOT_TOKEN", "123:abc")  # его подставляет bothost
    src = tmp_path / "s.yaml"
    src.write_text('bot: {owner_id: 42, allowed_user_ids: [7], digest_time: "09:30"}\n', encoding="utf-8")
    s = Settings.from_env(src)
    assert s.token == "123:abc" and s.owner_id == 42
    assert s.allowed_ids == {42, 7} and s.digest_time == "09:30"
    monkeypatch.setenv("OWNER_ID", "99")  # env приоритетнее
    assert Settings.from_env(src).owner_id == 99
