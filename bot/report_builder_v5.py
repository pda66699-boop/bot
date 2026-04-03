from __future__ import annotations

from typing import Any

from .business_language_adapter import adapt_business_language


def build_report_v5(
    assessment: dict[str, Any],
    data: dict[str, Any],
    report_mode: str = "extended_report",
) -> tuple[str, dict[str, Any]]:
    return adapt_business_language(assessment, data, report_mode=report_mode)
