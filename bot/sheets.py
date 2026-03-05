from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


class GoogleSheetsLogger:
    # Append-only журнал прогонов.
    COLUMN_ORDER = [
        "created_at",
        "run_id",
        "telegram_id",
        "username",
        "telegram_handle",
        "telegram_link",
        "full_name",
        "company",
        "revenue",
        "offer_opt_in",
        "stage",
        "nearest_stage",
        "profile_code",
        "transition",
        "hybrid",
        "regress",
        "idx_p",
        "idx_a",
        "idx_e",
        "idx_i",
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
        "warnings",
        "candidates_top3",
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

    def append_run_row(self, data_dict: dict[str, Any]) -> None:
        try:
            if not data_dict.get("run_id"):
                self.logger.warning("append_run_row skipped: missing run_id")
                return
            row = self._build_row(data_dict)
            self.ws.append_row(row, value_input_option="RAW")
        except Exception:
            self.logger.exception("Sheets append_run_row failed")

    def append_lead(self, payload: dict[str, Any]) -> None:
        self.append_run_row(payload)
