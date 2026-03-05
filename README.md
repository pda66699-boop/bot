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
  stage_map_v4.yaml
  stage_map_v3.yaml
  stage_map_v2.yaml
  report_templates_v3.yaml
  report_templates_v2.yaml
  dimensions.yaml
  questions_v2.yaml
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
  - `run_id` (новый UUID на каждое прохождение)
  - стадия + ближайшая альтернатива
  - `confidence` (0-100)
  - `transition/hybrid`, `regress`
  - профиль `PAEI`
  - индексы `P/A/E/I` (0-100)
  - описание, риски, рекомендации
  - история запусков append-only (без перезаписи прошлых результатов)

## Контракт результата (v4)

`report_json` / payload включает:
- `run_id`
- `stage`
- `second_best_stage`
- `nearest_stage` (legacy-совместимость: это тот же 2-й кандидат по distance)
- `profile_code`
- `indices`: `{P, A, E, I}`
- `confidence`
- `transition`
- `hybrid`
- `regress`
- `normal_problems`
- `abnormal_problems`
- `recommendations`
- `report_text`
- `warnings` (массив служебных предупреждений)
- `candidates` (top-3 кандидатов по distance: `[{stage, distance}, ...]`)

Правило регресса:
- учитывается только при наличии минимум 3 предыдущих запусков;
- текущая и предыдущая уверенность должны быть > 70;
- переход `Стабильность -> Расцвет` трактуется как восстановление, не регресс.

Стадии v4.1 (9):
1. Младенчество
2. Давай-давай
3. Юность
4. Ранний Расцвет
5. Расцвет
6. Стабильность
7. Аристократизм
8. Ранний бюрократизм
9. Бюрократия

Правило регистра профиля:
- индекс `>= 70` -> заглавная буква;
- индекс `< 70` -> строчная буква.
- пример: `P=72, A=61, E=67, I=83` -> `PaeI`.

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
