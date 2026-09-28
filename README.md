# Новостной бот

Telegram-бот: собирает новости из RSS / NewsAPI / публичных Telegram-каналов, **автоматически переводит иностранные на русский** (бесплатный Google, без ключа), убирает дубли и присылает утренний дайджест. Без LLM.

## Команды
`/news [тема]` · `/topics` · `/digest` · `/sources` · `/time ЧЧ:ММ` (только владелец). Чужим пользователям бот не отвечает.

## Запуск локально
```bash
pip install -r requirements-dev.txt
cp .env.example .env      # заполнить TELEGRAM_BOT_TOKEN и OWNER_ID
python main.py
python -m pytest          # тесты
```
Токен — новый, у @BotFather. Свой числовой ID можно узнать у @userinfobot.

## Источники
Правятся в `sources.yaml` (RSS, Telegram-каналы, NewsAPI, ключевые и стоп-слова). TechCrunch уже подключён.

## Деплой на bothost.ru
Проверено по [документации](https://bothost.ru/docs/): точка входа `main.py` находится автоматически, зависимости берутся из `requirements.txt`, кастомный Dockerfile включать не нужно (бот на long polling, порт не слушает).

1. Создать **приватный** репозиторий на GitHub/GitLab и запушить проект (`.env` в `.gitignore`).
2. bothost → «Создать бота» → Telegram → деплой из Git → выбрать репозиторий, ветка `main`. Поле main file оставить пустым.
3. Настройки:
   - **С переменными окружения** (платный тариф): `TELEGRAM_BOT_TOKEN`, `OWNER_ID`, `NEWSAPI_KEY` (опционально) — как в `.env.example`.
   - **Без них** (Starter, по FAQ env только на платных): токен bothost подставляет сам, а `owner_id` вписать в `sources.yaml` → `bot:` (это не секрет). NewsAPI на Starter не подключать — ключ в репозиторий не класть.
4. После старта в логах панели искать строку `network probe: ...` — она показывает, доступны ли с сервера Telegram, Google Translate, RSS и t.me.
5. Написать боту `/start`, `/digest`, `/sources`.

## Структура
```
main.py  config.py  sources.yaml
bot/      handlers.py (команды, allowlist), scheduler.py (сбор + дайджест)
core/     service.py, translate.py, normalize.py, dedupe.py, rank.py, digest.py
sources/  rss.py, tgchannel.py, newsapi.py
tests/
```
Состояние хранится только в памяти (на Starter диск стирается при рестарте): после перезапуска бот заново собирает ленты за последние часы.
