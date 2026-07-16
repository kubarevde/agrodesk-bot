# Telegram-бот АгроДеск

Автономный Python-сервис для **отдельного деплоя на bothost.ru**.

```
Telegram → Bot (bothost) → HTTPS → AgroDesk API → PostgreSQL
```

Полная инструкция: **[docs/bot-bothost.md](../docs/bot-bothost.md)**

## Быстрый старт

```bash
cd bot
pip install -r requirements.txt
cp bot.env.example .env
# заполнить BOT_TOKEN, API_BASE_URL, BOT_INTERNAL_SECRET
python scripts/self_check.py --telegram-id 111111111
python bot.py
```

## Env (обязательные)

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен @BotFather |
| `API_BASE_URL` | Публичный URL API (не localhost на bothost) |
| `BOT_INTERNAL_SECRET` | Общий секрет с backend |

На bothost: `AGRODESK_ENV=production`, `BOT_RUN_MODE=polling`.

Шаблоны: `.env.example`, `bot.env.example`.

## Entrypoint

```bash
python bot.py
```

## Self-check

```bash
python scripts/self_check.py --telegram-id 111111111
python scripts/self_check.py --telegram-id 111111111 --with-shifts  # dev only
```

## Режим

**Polling** — рекомендован для bothost.ru (исходящие запросы, автопереподключение).
