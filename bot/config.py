from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: Path
    data_dir: Path


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    db_path = Path(os.getenv("DB_PATH", "bot.db")).resolve()
    data_dir = Path(os.getenv("DATA_DIR", "data")).resolve()
    return Settings(bot_token=token, db_path=db_path, data_dir=data_dir)
