from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


class GoogleSheetsLogger:
    # Единая карта колонок нужна для постепенного обновления одной и той же строки.
    COLUMN_ORDER = [
        "created_at",
        "telegram_id",
        "username",
        "telegram_handle",
        "telegram_link",
        "full_name",
        "company",
        "revenue",
        "offer_opt_in",
        "stage",
        "second_stage",
        "confidence",
        "confidence_percent",
        "owner_dependency",
        "process_formalization",
        "management_contour",
        "stage_description",
        "risks",
        "do",
        "dont",
        "booking_prefill_text",
        "raw_stage_scores",
        "raw_answers",
        "answers_sheet_text",
        "status",
    ]

    def __init__(self, creds_path: str, sheet_name: str):
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        self.ws = client.open(sheet_name).sheet1
        self.logger = logging.getLogger(__name__)

    def _find_row_by_user_id(self, user_id: int) -> int | None:
        user_id_str = str(user_id)
        ids = self.ws.col_values(2)
        for idx, cell in enumerate(ids, start=1):
            if cell.strip() == user_id_str:
                return idx
        return None

    def _serialize_value(self, key: str, payload: dict[str, Any]) -> Any:
        if key == "created_at":
            return payload.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
        if key in {"risks", "do", "dont"}:
            items = payload.get(key, [])
            if isinstance(items, list):
                return "\n".join([f"- {x}" for x in items])
            return items or ""
        if key == "raw_stage_scores":
            data = payload.get("raw_stage_scores", payload.get("stage_scores", {}))
            return json.dumps(data, ensure_ascii=False)
        if key == "raw_answers":
            return json.dumps(payload.get("raw_answers", {}), ensure_ascii=False)
        return payload.get(key, "")

    def _build_row(self, payload: dict[str, Any]) -> list[Any]:
        return [self._serialize_value(key, payload) for key in self.COLUMN_ORDER]

    def ensure_user_row(self, user_data: dict[str, Any]) -> int:
        try:
            user_id = int(user_data["telegram_id"])
            row_num = self._find_row_by_user_id(user_id)
            if row_num is not None:
                return row_num
            row = self._build_row(user_data)
            self.ws.append_row(row, value_input_option="RAW")
            return self._find_row_by_user_id(user_id) or 1
        except Exception:
            self.logger.exception("Sheets ensure_user_row failed")
            return 1

    def update_user_row(self, user_id: int, data_dict: dict[str, Any]) -> None:
        try:
            row_num = self._find_row_by_user_id(user_id)
            if row_num is None:
                row_num = self.ensure_user_row({"telegram_id": user_id})

            # Обновляем только известные поля и пишем строку одним запросом.
            current = self.ws.row_values(row_num)
            row = current[:]
            if len(row) < len(self.COLUMN_ORDER):
                row.extend([""] * (len(self.COLUMN_ORDER) - len(row)))

            merged_payload = {"telegram_id": user_id, **data_dict}
            for idx, key in enumerate(self.COLUMN_ORDER):
                if key in data_dict:
                    row[idx] = self._serialize_value(key, merged_payload)

            self.ws.update(
                range_name=f"A{row_num}:{gspread.utils.rowcol_to_a1(row_num, len(self.COLUMN_ORDER))}",
                values=[row[: len(self.COLUMN_ORDER)]],
                value_input_option="RAW",
            )
        except Exception:
            self.logger.exception("Sheets update_user_row failed for user_id=%s", user_id)

    # Оставляем совместимость для старых вызовов: теперь это upsert в одну строку пользователя.
    def append_lead(self, payload: dict[str, Any]) -> None:
        try:
            user_id = int(payload["telegram_id"])
            self.ensure_user_row(payload)
            self.update_user_row(user_id, payload)
        except Exception:
            self.logger.exception("Sheets append_lead failed")
