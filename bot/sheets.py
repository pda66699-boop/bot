from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


class GoogleSheetsLogger:
    def __init__(self, creds_path: str, sheet_name: str):
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)
        self.ws = client.open(sheet_name).sheet1

    def append_lead(self, payload: dict[str, Any]) -> None:
        risks = payload.get("risks", [])
        do_items = payload.get("do", [])
        dont_items = payload.get("dont", [])

        row = [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            payload.get("telegram_id"),
            payload.get("username"),
            payload.get("telegram_handle"),
            payload.get("telegram_link"),
            payload.get("full_name"),
            payload.get("company"),
            payload.get("revenue"),
            payload.get("offer_opt_in"),
            payload.get("stage"),
            payload.get("second_stage"),
            payload.get("confidence"),
            payload.get("confidence_percent"),
            payload.get("owner_dependency"),
            payload.get("process_formalization"),
            payload.get("management_contour"),
            payload.get("stage_description"),
            "\n".join([f"- {x}" for x in risks]),
            "\n".join([f"- {x}" for x in do_items]),
            "\n".join([f"- {x}" for x in dont_items]),
            payload.get("booking_prefill_text"),
            json.dumps(payload.get("raw_stage_scores", payload.get("stage_scores", {})), ensure_ascii=False),
            json.dumps(payload.get("raw_answers", {}), ensure_ascii=False),
        ]
        self.ws.append_row(row, value_input_option="RAW")
