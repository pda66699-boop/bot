from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from .config import load_settings
from .flows import AppContext, create_router
from .scoring import load_data
from .sheets import GoogleSheetsLogger
from .storage import InMemoryStore, SQLiteStore


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    sheets = None
    if os.getenv("SHEETS_ENABLED", "0") == "1":
        sheets = GoogleSheetsLogger(
            creds_path=os.getenv("SHEETS_CREDS", "service_account.json"),
            sheet_name=os.getenv("SHEETS_NAME", "ApexSystem Bot Leads"),
        )

    data = load_data(settings.data_dir)
    sqlite = SQLiteStore(settings.db_path)
    memory = InMemoryStore()

    ctx = AppContext(data=data, sqlite=sqlite, memory=memory, sheets=sheets)
    router = create_router(ctx)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
