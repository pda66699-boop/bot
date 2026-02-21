# Adizes Stage Diagnostic Bot (MVP)

Telegram-бот на `aiogram 3` для диагностики стадии бизнеса по Адизесу.

## Структура проекта

```text
bot/
  main.py
  config.py
  storage.py
  scoring.py
  flows.py
  texts.py
data/
  stages.yaml
  dimensions.yaml
  questions.json
  bot_copy.md
README.md
requirements.txt
```

## Что умеет MVP

- `/start` + кнопка `Начать тест`
- 24 вопроса по одному через `inline keyboard`
- прогресс вида `Вопрос 7/24 ▓▓▓░░`
- сохранение ответов:
  - в памяти (текущая сессия)
  - в SQLite (`bot.db`)
- после теста сбор контактов:
  - Имя
  - TG (берется автоматически)
  - Выручка (кнопки диапазонов)
  - Кнопка `Поделиться ссылкой на мой Telegram` (для спецпредложения по детальному разбору)
- результат после заполнения контактов:
  - стадия
  - описание
  - риски
  - что делать / чего не делать
  - 3 индекса (0-100)
- CTA:
  - `Записаться на разбор`

## Локальный запуск (polling)

1. Создайте и активируйте виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Установите зависимости:

```bash
pip install -r requirements.txt
```

3. Задайте токен бота:

```bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
```

4. (Опционально) задайте путь к БД и данным:

```bash
export DB_PATH="./bot.db"
export DATA_DIR="./data"
```

5. Запустите бота:

```bash
python -m bot.main
```

Бот работает через polling. Вебхуки не используются.
