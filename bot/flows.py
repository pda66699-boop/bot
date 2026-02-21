from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Bot, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .scoring import (
    STAGE_ORDER,
    calculate_confidence,
    calculate_indices,
    calculate_stage_scores,
    select_winner,
)
from .storage import InMemoryStore, SQLiteStore
from .texts import (
    CONTACTS_INTRO,
    DURATION_TEXT,
    MOTIVATION_TEXT,
    START_TEXT,
)


class ContactForm(StatesGroup):
    name = State()
    revenue = State()


REVENUE_CHOICES = [
    ("rev_1", "До 1 млн ₽/мес"),
    ("rev_2", "1-5 млн ₽/мес"),
    ("rev_3", "5-20 млн ₽/мес"),
    ("rev_4", "20-100 млн ₽/мес"),
    ("rev_5", "100+ млн ₽/мес"),
]

REVENUE_MAP = {key: label for key, label in REVENUE_CHOICES}

STATUS_NOT_STARTED = "not_started"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED_NO_SHARE = "completed_no_share"
STATUS_COMPLETED_SHARED = "completed_shared"


@dataclass
class AppContext:
    data: dict[str, Any]
    sqlite: SQLiteStore
    memory: InMemoryStore
    sheets: Any | None = None


def _progress_bar(current: int, total: int, width: int = 5) -> str:
    filled = round(current / total * width)
    return "🟩" * filled + "🟨" * (width - filled)


def _question_emoji(question: dict[str, Any]) -> str:
    by_dimension = {
        "decisions": "🧠",
        "processes": "⚙️",
        "owner_dependency": "👤",
        "kpi_contour": "📊",
        "decision_speed": "⏱️",
        "roles_conflicts": "🤝",
        "growth_sustainability": "📈",
        "finance_predictability": "💰",
    }
    return by_dimension.get(question.get("dimension", ""), "🔹")


def _question_keyboard(question: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    for option in question["options"]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{option['key']}",
                    callback_data=f"ans:{question['id']}:{option['key']}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _revenue_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, label in REVENUE_CHOICES:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"rev:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _skip_keyboard(skip_key: str, title: str = "Пропустить") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=title, callback_data=skip_key)]]
    )


def _post_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Получить персональные рекомендации", callback_data="post_offer:yes")],
        ]
    )


def _build_result_text(
    winner_stage: dict[str, Any],
    second_stage_name: str,
    confidence: int,
    indices: dict[str, int],
) -> str:
    risks = "\n".join([f"- {x}" for x in winner_stage["risks"]])
    do = "\n".join([f"- {x}" for x in winner_stage["do"]])
    dont = "\n".join([f"- {x}" for x in winner_stage["dont"]])

    if confidence < 40:
        header = (
            "⚠ Бизнес в гибридной фазе развития.\n"
            f'Переход от стадии "{second_stage_name}" к "{winner_stage["name"]}"\n\n'
            "Признаки разных уровней зрелости сосуществуют одновременно."
        )
    else:
        header = f"<b>🏁 Ваша стадия: {winner_stage['name']}</b>"

    return (
        f"{header}\n\n"
        f"<b>🧭 Описание</b>\n{winner_stage['description']}\n\n"
        f"<b>⚠️ Ключевые риски</b>\n{risks}\n\n"
        f"<b>✅ Что делать</b>\n{do}\n\n"
        f"<b>⛔ Чего не делать</b>\n{dont}\n\n"
        f"<b>📈 Индексы (0-100)</b>\n"
        f"- Зависимость от собственника: {indices['owner_dependency']}\n"
        f"- Формализация процессов: {indices['process_formalization']}\n"
        f"- Управленческий контур: {indices['management_contour']}"
    )


def _build_booking_prefill_text(
    winner_stage: dict[str, Any],
    confidence: int,
    indices: dict[str, int],
    tg_handle: str,
) -> str:
    risks = "\n".join([f"- {x}" for x in winner_stage["risks"]])
    do = "\n".join([f"- {x}" for x in winner_stage["do"]])
    dont = "\n".join([f"- {x}" for x in winner_stage["dont"]])

    return (
        "Добрый день! Хочу получить полный разбор по итогам теста Адизеса.\n\n"
        f"Стадия: {winner_stage['name']}\n"
        f"Уверенность: {confidence}%\n"
        f"Индексы:\n"
        f"- Зависимость от собственника: {indices['owner_dependency']}\n"
        f"- Формализация процессов: {indices['process_formalization']}\n"
        f"- Управленческий контур: {indices['management_contour']}\n\n"
        "Выжимка:\n"
        f"Описание: {winner_stage['description']}\n\n"
        "Ключевые риски:\n"
        f"{risks}\n\n"
        "Что делать:\n"
        f"{do}\n\n"
        "Чего не делать:\n"
        f"{dont}\n\n"
        f"Мой Telegram: {tg_handle}"
    )


def _build_answers_sheet_text(
    questions: list[dict[str, Any]],
    answers: dict[str, str],
) -> str:
    lines: list[str] = []
    for idx, question in enumerate(questions, start=1):
        answer_key = answers.get(question["id"])
        answer_label = "Ответ не указан"
        if answer_key:
            option = next((opt for opt in question["options"] if opt["key"] == answer_key), None)
            if option:
                answer_label = option["label"]
        lines.append(
            f"{idx}. На вопрос «{question['text']}» респондент ответил: {answer_label}."
        )
    return "\n".join(lines)


def _tg_link_by_username(user_id: int, username: str | None) -> str:
    return f"https://t.me/{username}" if username else f"tg://user?id={user_id}"


async def _send_delayed_offer_message(bot: Bot, chat_id: int) -> None:
    await asyncio.sleep(300)
    text = (
        "🎁 Предложение еще в силе!\n\n"
        "В отчёте Вы уже получили рекомендации и наблюдения,\n"
        "которые помогут укрепить управляемость и сократить потери.\n\n"
        "Но общий отчет показывает стадию и характерные для нее особенности.\n"
        "Если хотите персональный разьор, исходя из ваших ответов — нажмите кнопку ниже"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=_post_offer_keyboard())
    except Exception:
        # Ошибка отложенной отправки не должна ломать основной сценарий.
        pass


async def _send_current_question(message: Message, ctx: AppContext, user_id: int) -> None:
    session = ctx.memory.get_or_create(user_id)
    questions = ctx.data["questions"]
    question = questions[session.current_index]
    pos = session.current_index + 1
    total = len(questions)
    bar = _progress_bar(pos, total)
    marker = _question_emoji(question)

    options_text = "\n".join(
        [f"<b>{opt['key']}.</b> {opt['label']}" for opt in question["options"]]
    )
    text = (
        f"<b>Вопрос {pos}/{total} {bar}</b>\n\n"
        f"{marker} {question['text']}\n\n"
        f"{options_text}"
    )
    await message.answer(text, reply_markup=_question_keyboard(question))


def create_router(ctx: AppContext) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        user = message.from_user
        if not user:
            return
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        ctx.sqlite.save_user(user.id, user.username, full_name)
        ctx.sqlite.set_status(user.id, STATUS_NOT_STARTED)
        ctx.memory.reset(user.id)
        ctx.sqlite.clear_answers(user.id)
        await state.clear()
        if ctx.sheets:
            ctx.sheets.ensure_user_row(
                {
                    "telegram_id": user.id,
                    "username": user.username or "",
                    "telegram_handle": f"@{user.username}" if user.username else f"id:{user.id}",
                    "telegram_link": _tg_link_by_username(user.id, user.username),
                    "full_name": full_name,
                    "status": STATUS_NOT_STARTED,
                    "raw_answers": {},
                }
            )
            ctx.sheets.update_user_row(
                user.id,
                {
                    "username": user.username or "",
                    "telegram_handle": f"@{user.username}" if user.username else f"id:{user.id}",
                    "telegram_link": _tg_link_by_username(user.id, user.username),
                    "full_name": full_name,
                    "status": STATUS_NOT_STARTED,
                    "raw_answers": {},
                },
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🚀 Начать тест", callback_data="start_test")]]
        )
        await message.answer(
            f"{START_TEXT}\n\n{DURATION_TEXT}\n\n{MOTIVATION_TEXT}",
            reply_markup=kb,
        )

    @router.callback_query(F.data == "start_test")
    async def start_test(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        ctx.memory.reset(user.id)
        ctx.sqlite.clear_answers(user.id)
        await state.clear()
        try:
            await callback.answer()
        except Exception:
            pass
        if callback.message:
            await callback.message.answer("🚀 Начинаем тест.")
            await _send_current_question(callback.message, ctx, user.id)

    @router.callback_query(F.data.startswith("ans:"))
    async def answer_question(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        try:
            await callback.answer()
        except Exception:
            pass

        parts = callback.data.split(":")
        if len(parts) != 3:
            return

        _, question_id, option_key = parts
        session = ctx.memory.get_or_create(user.id)
        questions = ctx.data["questions"]

        if session.current_index >= len(questions):
            return

        expected_qid = questions[session.current_index]["id"]
        if question_id != expected_qid:
            return

        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)

        session.answers[question_id] = option_key
        ctx.sqlite.save_answer(user.id, question_id, option_key)
        ctx.sqlite.set_status(user.id, STATUS_IN_PROGRESS)
        if ctx.sheets:
            ctx.sheets.update_user_row(
                user.id,
                {
                    "username": user.username or "",
                    "telegram_handle": f"@{user.username}" if user.username else f"id:{user.id}",
                    "telegram_link": _tg_link_by_username(user.id, user.username),
                    "raw_answers": session.answers,
                    "status": STATUS_IN_PROGRESS,
                },
            )
        session.current_index += 1

        if session.current_index < len(questions):
            if callback.message:
                await _send_current_question(callback.message, ctx, user.id)
            return

        ctx.sqlite.set_status(user.id, STATUS_COMPLETED_NO_SHARE)
        if ctx.sheets:
            ctx.sheets.update_user_row(
                user.id,
                {
                    "status": STATUS_COMPLETED_NO_SHARE,
                    "raw_answers": session.answers,
                },
            )
        await state.set_state(ContactForm.name)
        if callback.message:
            await callback.message.answer(
                f"{CONTACTS_INTRO}\n\n👤 Введите имя:",
            )
    @router.message(ContactForm.name)
    async def contact_name(message: Message, state: FSMContext) -> None:
        await state.update_data(name=message.text.strip())
        if ctx.sheets and message.from_user:
            ctx.sheets.update_user_row(
                message.from_user.id,
                {"full_name": message.text.strip(), "status": STATUS_COMPLETED_NO_SHARE},
            )
        await state.set_state(ContactForm.revenue)
        await message.answer("💰 Выберите диапазон выручки:", reply_markup=_revenue_keyboard())

    @router.callback_query(ContactForm.revenue, F.data.startswith("rev:"))
    async def contact_revenue(callback: CallbackQuery, state: FSMContext) -> None:
        key = callback.data.split(":")[1]
        revenue = REVENUE_MAP.get(key, key)
        await state.update_data(revenue=revenue, offer_opt_in=False, tg_link=None)
        if ctx.sheets:
            ctx.sheets.update_user_row(
                callback.from_user.id,
                {"revenue": revenue, "status": STATUS_COMPLETED_NO_SHARE},
            )
        await callback.answer()
        if callback.message:
            await _finalize_and_show_result(callback.message, callback.from_user.id, state, ctx)

    @router.callback_query(F.data == "post_offer:yes")
    async def post_offer_yes(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        tg_link = _tg_link_by_username(user.id, user.username)
        ctx.sqlite.update_offer_opt_in(user.id, tg_link=tg_link, offer_opt_in=True)
        ctx.sqlite.set_status(user.id, STATUS_COMPLETED_SHARED)
        if ctx.sheets:
            ctx.sheets.update_user_row(
                user.id,
                {"offer_opt_in": True, "telegram_link": tg_link, "status": STATUS_COMPLETED_SHARED},
            )
        await callback.answer("Отлично, свяжемся с вами в Telegram ✅")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Принято. Скоро отправим персональные рекомендации в Telegram.")

    return router


async def _finalize_and_show_result(
    message: Message,
    user_id: int,
    state: FSMContext,
    ctx: AppContext,
) -> None:
    form = await state.get_data()
    db_username = ctx.sqlite.get_username(user_id)
    user = SimpleNamespace(username=db_username) if db_username else message.from_user
    tg_handle = f"@{db_username}" if db_username else f"id:{user_id}"
    respondent_tg_link = form.get("tg_link") or (
        f"https://t.me/{db_username}" if db_username else f"tg://user?id={user_id}"
    )

    ctx.sqlite.save_contacts(
        user_id,
        name=form.get("name", "").strip(),
        telegram=tg_handle,
        company="Не указано",
        revenue=form.get("revenue", "").strip(),
        tg_link=respondent_tg_link,
        offer_opt_in=bool(form.get("offer_opt_in")),
    )

    session = ctx.memory.get_or_create(user_id)
    session.contacts = form
    answers = session.answers or ctx.sqlite.get_answers(user_id)

    stage_scores = calculate_stage_scores(answers, ctx.data["questions_by_id"])
    winner_name, winner_score, runner_up_score = select_winner(
        stage_scores,
        answers,
        ctx.data["questions_by_id"],
    )
    stage_scores_sorted = sorted(stage_scores.items(), key=lambda x: x[1], reverse=True)
    second_stage_name = next((name for name, _ in stage_scores_sorted if name != winner_name), winner_name)
    confidence = calculate_confidence(winner_score, runner_up_score, sum(stage_scores.values()))
    indices = calculate_indices(answers)
    winner_stage = ctx.data["stage_by_name"][winner_name]

    text = _build_result_text(winner_stage, second_stage_name, confidence, indices)
    booking_prefill = _build_booking_prefill_text(
        winner_stage,
        confidence,
        indices,
        respondent_tg_link,
    )
    telegram_link = (
        f"https://t.me/{user.username}"
        if user and user.username
        else f"tg://user?id={user_id}"
    )
    if ctx.sheets:
        answers_sheet_text = _build_answers_sheet_text(ctx.data["questions"], answers)
        ctx.sheets.ensure_user_row(
            {
                "telegram_id": user_id,
                "username": (user.username if user else None),
            }
        )
        ctx.sheets.update_user_row(user_id, {
            "telegram_id": user_id,
            "username": (user.username if user else None),
            "telegram_link": telegram_link,
            "telegram_handle": tg_handle,
            "full_name": form.get("name"),
            "company": "Не указано",
            "revenue": form.get("revenue"),
            "offer_opt_in": bool(form.get("offer_opt_in")),
            "stage": winner_stage["name"],
            "second_stage": second_stage_name,
            "confidence": confidence,
            "confidence_percent": confidence,
            "owner_dependency": indices["owner_dependency"],
            "process_formalization": indices["process_formalization"],
            "management_contour": indices["management_contour"],
            "stage_description": winner_stage["description"],
            "risks": winner_stage["risks"],
            "do": winner_stage["do"],
            "dont": winner_stage["dont"],
            "stage_scores": stage_scores,
            "raw_stage_scores": stage_scores,
            "booking_prefill_text": booking_prefill,
            "raw_answers": answers,
            "answers_sheet_text": answers_sheet_text,
            "status": ctx.sqlite.get_status(user_id),
        })

    admin_id = os.getenv("ADMIN_ID")

    if admin_id:
        respondent_name = (form.get("name") or "").strip() or "Не указано"
        respondent_revenue = (form.get("revenue") or "").strip() or "Не указано"
        shared_tg = bool(form.get("offer_opt_in"))
        risks_text = "\n".join([f"- {x}" for x in winner_stage["risks"]])
        do_text = "\n".join([f"- {x}" for x in winner_stage["do"]])
        dont_text = "\n".join([f"- {x}" for x in winner_stage["dont"]])

        summary = (
            f"🆕 Новый респондент\n\n"
            f"👤 Имя: {respondent_name}\n"
            f"💰 Выручка: {respondent_revenue}\n"
            f"📨 Поделился ссылкой на Telegram: {'Да' if shared_tg else 'Нет'}\n\n"
            f"📊 Победившая стадия: {winner_stage['name']}\n"
            f"📊 Вторая стадия: {second_stage_name}\n"
            f"📈 Уверенность результата: {confidence}%\n\n"
            f"🔹 Зависимость от собственника: {indices['owner_dependency']}\n"
            f"🔹 Формализация процессов: {indices['process_formalization']}\n"
            f"🔹 Управленческий контур: {indices['management_contour']}\n\n"
            f"🧮 Баллы по стадиям:\n"
            f"{chr(10).join([f'- {stage}: {stage_scores.get(stage, 0)}' for stage in STAGE_ORDER])}\n\n"
            f"🧭 Описание:\n{winner_stage['description']}\n\n"
            f"⚠️ Риски:\n{risks_text}\n\n"
            f"✅ Что делать:\n{do_text}\n\n"
            f"⛔ Чего не делать:\n{dont_text}\n\n"
            f"🔗 Профиль: {telegram_link}"
        )

        await message.bot.send_message(
            chat_id=int(admin_id),
            text=summary,
        )
    await message.answer(text)
    asyncio.create_task(_send_delayed_offer_message(message.bot, user_id))
    await state.clear()
