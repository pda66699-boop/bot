from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


@dataclass
class UserSession:
    current_index: int = 0
    answers: dict[str, str] = field(default_factory=dict)
    contacts: dict[str, Any] = field(default_factory=dict)


class InMemoryStore:
    def __init__(self) -> None:
        self._sessions: dict[int, UserSession] = {}

    def reset(self, user_id: int) -> UserSession:
        self._sessions[user_id] = UserSession()
        return self._sessions[user_id]

    def get_or_create(self, user_id: int) -> UserSession:
        if user_id not in self._sessions:
            self._sessions[user_id] = UserSession()
        return self._sessions[user_id]


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              tg_id INTEGER PRIMARY KEY,
              username TEXT,
              full_name TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS answers (
              tg_id INTEGER NOT NULL,
              question_id TEXT NOT NULL,
              option_key TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (tg_id, question_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
              tg_id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              telegram TEXT NOT NULL,
              company TEXT NOT NULL,
              revenue TEXT NOT NULL,
              tg_link TEXT,
              offer_opt_in INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            )
            """
        )
        self._ensure_column("contacts", "tg_link", "TEXT")
        self._ensure_column("contacts", "offer_opt_in", "INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def save_user(self, tg_id: int, username: str | None, full_name: str) -> None:
        self.conn.execute(
            """
            INSERT INTO users(tg_id, username, full_name, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
              username=excluded.username,
              full_name=excluded.full_name,
              updated_at=excluded.updated_at
            """,
            (tg_id, username or "", full_name, _now_iso()),
        )
        self.conn.commit()

    def clear_answers(self, tg_id: int) -> None:
        self.conn.execute("DELETE FROM answers WHERE tg_id = ?", (tg_id,))
        self.conn.commit()

    def save_answer(self, tg_id: int, question_id: str, option_key: str) -> None:
        self.conn.execute(
            """
            INSERT INTO answers(tg_id, question_id, option_key, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(tg_id, question_id) DO UPDATE SET
              option_key=excluded.option_key,
              updated_at=excluded.updated_at
            """,
            (tg_id, question_id, option_key, _now_iso()),
        )
        self.conn.commit()

    def get_answers(self, tg_id: int) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT question_id, option_key FROM answers WHERE tg_id = ?",
            (tg_id,),
        ).fetchall()
        return {row["question_id"]: row["option_key"] for row in rows}

    def get_username(self, tg_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT username FROM users WHERE tg_id = ?",
            (tg_id,),
        ).fetchone()
        if not row:
            return None
        username = (row["username"] or "").strip()
        return username or None

    def save_contacts(
        self,
        tg_id: int,
        *,
        name: str,
        telegram: str,
        company: str,
        revenue: str,
        tg_link: str | None,
        offer_opt_in: bool,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO contacts(tg_id, name, telegram, company, revenue, tg_link, offer_opt_in, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
              name=excluded.name,
              telegram=excluded.telegram,
              company=excluded.company,
              revenue=excluded.revenue,
              tg_link=excluded.tg_link,
              offer_opt_in=excluded.offer_opt_in,
              updated_at=excluded.updated_at
            """,
            (tg_id, name, telegram, company, revenue, tg_link, int(offer_opt_in), _now_iso()),
        )
        self.conn.commit()
