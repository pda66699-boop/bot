from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from .scoring import evaluate_assessment
from .storage import InMemoryStore, SQLiteStore
from .texts import CONTACTS_INTRO, DURATION_TEXT, MOTIVATION_TEXT, START_TEXT


class ContactForm(StatesGroup):
    name = State()
    revenue = State()
    tg_share = State()


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
MENU_START_TEST = "Пройти тест"
MENU_MY_RESULTS = "Мои результаты"


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
        "P": "📦",
        "A": "⚙️",
        "E": "🚀",
        "I": "🤝",
    }
    return by_dimension.get(question.get("dim", ""), "🔹")


def _shuffled_options(question: dict[str, Any], user_id: int) -> list[dict[str, Any]]:
    options = list(question["options"])
    original = list(options)
    rnd = random.Random(f"{user_id}:{question['id']}")
    rnd.shuffle(options)
    if options == original and len(options) > 1:
        options = options[1:] + options[:1]
    return options


def _display_choices(options: list[dict[str, Any]]) -> list[dict[str, str]]:
    display_keys = ["A", "B", "C", "D"]
    choices: list[dict[str, str]] = []
    for idx, option in enumerate(options):
        choices.append(
            {
                "display_key": display_keys[idx] if idx < len(display_keys) else str(idx + 1),
                "option_key": option["key"],
                "label": option["label"],
            }
        )
    return choices


def _question_keyboard(question: dict[str, Any], choices: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows = []
    for choice in choices:
        rows.append(
            [
                InlineKeyboardButton(
                    text=choice["display_key"],
                    callback_data=f"ans:{question['id']}:{choice['option_key']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back"),
            InlineKeyboardButton(text="✖️ Отмена", callback_data="nav:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_START_TEST)],
            [KeyboardButton(text=MENU_MY_RESULTS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def _revenue_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, label in REVENUE_CHOICES:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"rev:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tg_share_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Получить разбор", callback_data="tgshare:yes")],
            [InlineKeyboardButton(text="Пропустить", callback_data="tgshare:no")],
        ]
    )


def _post_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Получить персональные рекомендации", callback_data="post_offer:yes")],
        ]
    )


def _build_booking_prefill_text(assessment: dict[str, Any], tg_handle: str) -> str:
    indices = assessment["indices"]
    second_best_line = (
        f"2-й кандидат по distance: {assessment['second_best_stage']}\n"
        if assessment.get("second_best_stage") and assessment["second_best_stage"] != assessment["stage"]
        else ""
    )
    return (
        "Добрый день! Хочу получить полный разбор по итогам теста Адизеса.\n\n"
        f"Стадия: {assessment['stage']}\n"
        f"{second_best_line}"
        f"Профиль: {assessment['profile_code']}\n"
        f"Переход: {'да' if assessment['transition'] else 'нет'}\n"
        f"Гибрид: {'да' if assessment['hybrid'] else 'нет'}\n"
        f"Уверенность: {assessment['confidence']}%\n"
        f"Регресс: {'да' if assessment['regress'] else 'нет'}\n"
        f"Warnings: {', '.join(assessment.get('warnings', [])) or 'нет'}\n"
        "Индексы:\n"
        f"- P: {indices['P']}\n"
        f"- A: {indices['A']}\n"
        f"- E: {indices['E']}\n"
        f"- I: {indices['I']}\n\n"
        f"Мой Telegram: {tg_handle}"
    )


def _build_admin_summary_text(
    assessment: dict[str, Any],
    run_id: str,
    respondent_name: str,
    respondent_revenue: str,
    shared_tg: bool,
    telegram_link: str,
) -> str:
    idx = assessment["indices"]
    second_best_line = (
        f"📊 2-й кандидат по distance: {assessment['second_best_stage']}\n"
        if assessment.get("second_best_stage") and assessment["second_best_stage"] != assessment["stage"]
        else ""
    )
    return (
        "🆕 Новый респондент\n\n"
        f"👤 Имя: {respondent_name}\n"
        f"💰 Выручка: {respondent_revenue}\n"
        f"📨 Поделился ссылкой на Telegram: {'Да' if shared_tg else 'Нет'}\n\n"
        f"📊 Стадия: {assessment['stage']}\n"
        f"{second_best_line}"
        f"🆔 Run ID: {run_id}\n"
        f"🧬 Профиль PAEI: {assessment['profile_code']}\n"
        f"↔️ Переход: {'да' if assessment['transition'] else 'нет'}\n"
        f"🧩 Гибрид: {'да' if assessment['hybrid'] else 'нет'}\n"
        f"🎯 Уверенность: {assessment['confidence']}%\n"
        f"⏪ Регресс: {'да' if assessment['regress'] else 'нет'}\n\n"
        f"⚠️ Warnings: {', '.join(assessment.get('warnings', [])) or 'нет'}\n"
        f"📈 Индексы: P={idx['P']}, A={idx['A']}, E={idx['E']}, I={idx['I']}\n"
        f"🧮 Дистанции до стадий: {assessment.get('distances', {})}\n\n"
        f"🔗 Профиль: {telegram_link}"
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
        lines.append(f"{idx}. На вопрос «{question['text']}» респондент ответил: {answer_label}.")
    return "\n".join(lines)


def _tg_link_by_username(user_id: int, username: str | None) -> str:
    return f"https://t.me/{username}" if username else f"tg://user?id={user_id}"


def _format_result_date(raw_value: str) -> str:
    try:
        dt = datetime.fromisoformat(raw_value)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return raw_value or "-"


def _build_my_results_text(history: list[dict[str, Any]]) -> str:
    dim_name = {
        "P": "результат и клиент",
        "A": "системность",
        "E": "развитие",
        "I": "командная связность",
    }

    def _skew(indices: dict[str, int]) -> str:
        if not indices or all(int(v or 0) == 0 for v in indices.values()):
            return "перекос: данные по индексам недоступны"
        max_key = max(("P", "A", "E", "I"), key=lambda k: int(indices.get(k, 0) or 0))
        min_key = min(("P", "A", "E", "I"), key=lambda k: int(indices.get(k, 0) or 0))
        return f"перекос: сильная {max_key} ({dim_name[max_key]}), слабая {min_key} ({dim_name[min_key]})"

    if not history:
        return "🗂 У вас пока нет завершённых прохождений теста.\n\nНажмите «Пройти тест»."
    lines = ["🗂 Ваши последние результаты:\n"]
    for idx, row in enumerate(history[:5], start=1):
        indices = row.get("indices", {}) or {}
        profile = row.get("profile_code") or "-"
        indices_line = (
            f"P={int(indices.get('P', 0) or 0)}, "
            f"A={int(indices.get('A', 0) or 0)}, "
            f"E={int(indices.get('E', 0) or 0)}, "
            f"I={int(indices.get('I', 0) or 0)}"
        )
        lines.append(
            f"{idx}. {_format_result_date(str(row.get('created_at', '')))} — "
            f"{row.get('stage', '—')} (уверенность: {int(row.get('confidence', 0) or 0)}%)\n"
            f"   PAEI: {profile}\n"
            f"   Индексы: {indices_line}\n"
            f"   {_skew(indices)}"
        )
    return "\n".join(lines)


async def _start_test_flow(message: Message, state: FSMContext, ctx: AppContext, user_id: int) -> None:
    ctx.memory.reset(user_id)
    ctx.sqlite.clear_answers(user_id)
    ctx.sqlite.set_status(user_id, STATUS_IN_PROGRESS)
    await state.clear()
    await message.answer("🚀 Начинаем тест.", reply_markup=_main_menu_keyboard())
    await _send_current_question(message, ctx, user_id)


async def _send_delayed_offer_message(bot: Bot, chat_id: int) -> None:
    await asyncio.sleep(300)
    text = (
        "🎁 Предложение еще в силе!\n\n"
        "В отчёте Вы уже получили рекомендации и наблюдения,\n"
        "которые помогут укрепить управляемость и сократить потери.\n\n"
        "Но общий отчет показывает лишь стадию развития и характерные для нее особенности.\n"
        "Если хотите персональный разбор, основанный на выбранных вариантах ответов — нажмите кнопку ниже"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=_post_offer_keyboard())
    except Exception:
        pass


async def _send_current_question(message: Message, ctx: AppContext, user_id: int) -> None:
    session = ctx.memory.get_or_create(user_id)
    questions = ctx.data["questions"]
    question = questions[session.current_index]
    options = _shuffled_options(question, user_id)
    choices = _display_choices(options)
    pos = session.current_index + 1
    total = len(questions)
    bar = _progress_bar(pos, total)
    marker = _question_emoji(question)

    options_text = "\n".join([f"<b>{ch['display_key']}.</b> {ch['label']}" for ch in choices])
    text = (
        f"<b>Вопрос {pos}/{total} {bar}</b>\n\n"
        f"{marker} {question['text']}\n\n"
        f"{options_text}"
    )
    await message.answer(text, reply_markup=_question_keyboard(question, choices))


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

        await message.answer(
            f"{START_TEXT}\n\n{DURATION_TEXT}\n\n{MOTIVATION_TEXT}",
            reply_markup=_main_menu_keyboard(),
        )

    @router.callback_query(F.data == "start_test")
    async def start_test(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        try:
            await callback.answer()
        except Exception:
            pass
        if callback.message:
            await _start_test_flow(callback.message, state, ctx, user.id)

    @router.message(F.text == MENU_START_TEST)
    async def start_test_from_menu(message: Message, state: FSMContext) -> None:
        user = message.from_user
        if not user:
            return
        await _start_test_flow(message, state, ctx, user.id)

    @router.message(F.text == MENU_MY_RESULTS)
    async def my_results_from_menu(message: Message) -> None:
        user = message.from_user
        if not user:
            return
        history = ctx.sqlite.get_recent_results(user.id, limit=5)
        await message.answer(_build_my_results_text(history), reply_markup=_main_menu_keyboard())

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
        session.current_index += 1

        if session.current_index < len(questions):
            if callback.message:
                await _send_current_question(callback.message, ctx, user.id)
            return

        ctx.sqlite.set_status(user.id, STATUS_COMPLETED_NO_SHARE)
        await state.set_state(ContactForm.name)
        if callback.message:
            await callback.message.answer(f"{CONTACTS_INTRO}\n\n👤 Введите имя:")

    @router.callback_query(F.data == "nav:back")
    async def nav_back(callback: CallbackQuery) -> None:
        user = callback.from_user
        session = ctx.memory.get_or_create(user.id)
        if session.current_index <= 0:
            await callback.answer("Это первый вопрос", show_alert=False)
            return
        session.current_index -= 1
        ctx.sqlite.set_status(user.id, STATUS_IN_PROGRESS)
        await callback.answer("Вернулись на предыдущий вопрос")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await _send_current_question(callback.message, ctx, user.id)

    @router.callback_query(F.data == "nav:cancel")
    async def nav_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        ctx.memory.reset(user.id)
        ctx.sqlite.clear_answers(user.id)
        ctx.sqlite.set_status(user.id, STATUS_NOT_STARTED)
        await state.clear()
        await callback.answer("Тест отменён")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Тест отменён. Выберите действие:", reply_markup=_main_menu_keyboard())

    @router.message(ContactForm.name)
    async def contact_name(message: Message, state: FSMContext) -> None:
        await state.update_data(name=message.text.strip())
        await state.set_state(ContactForm.revenue)
        await message.answer("💰 Выберите диапазон выручки:", reply_markup=_revenue_keyboard())

    @router.callback_query(ContactForm.revenue, F.data.startswith("rev:"))
    async def contact_revenue(callback: CallbackQuery, state: FSMContext) -> None:
        key = callback.data.split(":")[1]
        revenue = REVENUE_MAP.get(key, key)
        await state.update_data(revenue=revenue, offer_opt_in=False, tg_link=None)
        await state.set_state(ContactForm.tg_share)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "🎁 Хотите получить более точные рекомендации на основе Ваших ответов?\n"
                "Нажмите кнопку ниже, и мы направим их вам в Telegram",
                reply_markup=_tg_share_keyboard(),
            )

    @router.callback_query(ContactForm.tg_share, F.data == "tgshare:no")
    async def tg_share_no(callback: CallbackQuery, state: FSMContext) -> None:
        await state.update_data(offer_opt_in=False, tg_link=None)
        ctx.sqlite.set_status(callback.from_user.id, STATUS_COMPLETED_NO_SHARE)
        await callback.answer()
        if callback.message:
            await _finalize_and_show_result(callback.message, callback.from_user.id, state, ctx)

    @router.callback_query(ContactForm.tg_share, F.data == "tgshare:yes")
    async def tg_share_yes(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        tg_link = _tg_link_by_username(user.id, user.username)
        await state.update_data(offer_opt_in=True, tg_link=tg_link)
        ctx.sqlite.set_status(user.id, STATUS_COMPLETED_SHARED)
        await callback.answer("Ссылка сохранена ✅")
        if callback.message:
            await _finalize_and_show_result(callback.message, user.id, state, ctx)

    @router.callback_query(F.data == "post_offer:yes")
    async def post_offer_yes(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        tg_link = _tg_link_by_username(user.id, user.username)
        ctx.sqlite.update_offer_opt_in(user.id, tg_link=tg_link, offer_opt_in=True)
        ctx.sqlite.set_status(user.id, STATUS_COMPLETED_SHARED)
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
    respondent_username = db_username
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

    run_id = str(uuid4())
    history = ctx.sqlite.get_recent_results(user_id, limit=5)
    assessment = evaluate_assessment(answers, ctx.data, history=history)
    ctx.sqlite.save_result(
        user_id,
        assessment["stage"],
        run_id,
        assessment["confidence"],
        bool(assessment["regress"]),
        assessment.get("profile_code"),
        assessment.get("indices"),
    )

    text = assessment["report_text"]
    booking_prefill = _build_booking_prefill_text(assessment, respondent_tg_link)
    telegram_link = respondent_tg_link

    if ctx.sheets:
        answers_sheet_text = _build_answers_sheet_text(ctx.data["questions"], answers)
        winner_stage = ctx.data["stage_by_name"][assessment["stage"]]
        ctx.sheets.append_run_row(
            {
                "telegram_id": user_id,
                "username": respondent_username,
                "telegram_link": telegram_link,
                "telegram_handle": tg_handle,
                "full_name": form.get("name"),
                "company": "Не указано",
                "revenue": form.get("revenue"),
                "offer_opt_in": bool(form.get("offer_opt_in")),
                "stage": assessment["stage"],
                "nearest_stage": assessment["second_best_stage"],
                "run_id": run_id,
                "profile_code": assessment["profile_code"],
                "transition": bool(assessment["transition"]),
                "hybrid": assessment["hybrid"],
                "regress": assessment["regress"],
                "confidence": assessment["confidence"],
                "warnings": ", ".join(assessment.get("warnings", [])),
                "candidates_top3": ", ".join(
                    [f"{idx + 1}) {item['stage']} ({item['distance']})" for idx, item in enumerate(assessment.get("candidates", [])[:3])]
                ),
                "idx_p": assessment["indices"]["P"],
                "idx_a": assessment["indices"]["A"],
                "idx_e": assessment["indices"]["E"],
                "idx_i": assessment["indices"]["I"],
                "stage_description": winner_stage.get("description", ""),
                "risks": winner_stage.get("risks", []),
                "do": winner_stage.get("next_actions_base", []),
                "dont": winner_stage.get("dont", []),
                "raw_stage_scores": assessment.get("distances", {}),
                "booking_prefill_text": booking_prefill,
                "raw_answers": answers,
                "answers_sheet_text": answers_sheet_text,
                "status": ctx.sqlite.get_status(user_id),
            },
        )

    admin_id = os.getenv("ADMIN_ID")
    if admin_id:
        respondent_name = (form.get("name") or "").strip() or "Не указано"
        respondent_revenue = (form.get("revenue") or "").strip() or "Не указано"
        shared_tg = bool(form.get("offer_opt_in"))
        summary = _build_admin_summary_text(
            assessment=assessment,
            run_id=run_id,
            respondent_name=respondent_name,
            respondent_revenue=respondent_revenue,
            shared_tg=shared_tg,
            telegram_link=telegram_link,
        )
        await message.bot.send_message(chat_id=int(admin_id), text=summary)

    await message.answer(text)
    asyncio.create_task(_send_delayed_offer_message(message.bot, user_id))
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=_main_menu_keyboard())
