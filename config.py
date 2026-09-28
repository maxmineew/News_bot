"""Настройки из переменных окружения (.env) и источники из sources.yaml."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def _clean_value(raw: str) -> str:
    """Убирает кавычки и комментарий после значения (`KEY=value   # пояснение`)."""
    value = raw.strip()
    if value[:1] in ("'", '"') and value.count(value[0]) >= 2:
        return value[1:value.index(value[0], 1)]
    if value.startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Минимальный загрузчик .env; уже заданные переменные не перезаписываются."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _clean_value(value))


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(";", ",").split(",") if x.strip().isdigit()}


@dataclass
class Settings:
    token: str
    owner_id: int
    allowed_ids: set[int] = field(default_factory=set)
    newsapi_key: str = ""
    digest_time: str = "08:00"
    tz: str = "Europe/Moscow"
    log_level: str = "INFO"
    translate_daily_chars: int = 200_000
    refresh_minutes: int = 30

    @classmethod
    def from_env(cls, sources_path: Path = ROOT / "sources.yaml") -> "Settings":
        load_dotenv()
        # На Starter env-переменных может не быть: токен bothost подставляет сам
        # (BOT_TOKEN / API_TOKEN), а несекретные настройки берём из sources.yaml -> bot:
        bot = (yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}).get("bot") or {}
        token = next(
            (os.environ[k].strip() for k in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "API_TOKEN")
             if os.environ.get(k, "").strip()),
            "",
        )
        owner = os.environ.get("OWNER_ID", "").strip() or str(bot.get("owner_id") or "")
        if not token or not owner.isdigit() or int(owner) == 0:
            raise SystemExit(
                "Нужны токен бота и числовой OWNER_ID: переменные окружения "
                "TELEGRAM_BOT_TOKEN/OWNER_ID или bot.owner_id в sources.yaml"
            )
        owner_id = int(owner)
        extra = os.environ.get("ALLOWED_USER_IDS", "") or ",".join(map(str, bot.get("allowed_user_ids") or []))
        return cls(
            token=token,
            owner_id=owner_id,
            allowed_ids=_ids(extra) | {owner_id},
            newsapi_key=os.environ.get("NEWSAPI_KEY", "").strip(),
            digest_time=os.environ.get("DIGEST_TIME", "").strip() or str(bot.get("digest_time") or "08:00"),
            tz=os.environ.get("TZ", "").strip() or str(bot.get("tz") or "Europe/Moscow"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            translate_daily_chars=int(os.environ.get("TRANSLATE_DAILY_CHARS", "200000")),
            refresh_minutes=int(os.environ.get("REFRESH_MINUTES", "30")),
        )


@dataclass
class SourcesConfig:
    rss: list[dict] = field(default_factory=list)
    telegram: list[dict] = field(default_factory=list)
    newsapi: dict = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    stopwords: list[str] = field(default_factory=list)
    per_topic: int = 5
    max_age_hours: int = 24
    max_articles: int = 2000

    @classmethod
    def load(cls, path: Path = ROOT / "sources.yaml") -> "SourcesConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        digest = data.get("digest", {})
        return cls(
            rss=data.get("rss", []),
            telegram=data.get("telegram", []),
            newsapi=data.get("newsapi", {}),
            keywords=data.get("keywords", []),
            stopwords=data.get("stopwords", []),
            per_topic=digest.get("per_topic", 5),
            max_age_hours=digest.get("max_age_hours", 24),
            max_articles=digest.get("max_articles", 2000),
        )
