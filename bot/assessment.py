from __future__ import annotations

from pathlib import Path
from typing import Any

from .assessment_engine_v5 import evaluate_assessment_v5, load_v5_data, use_v5_engine
from .scoring import evaluate_assessment as evaluate_assessment_v4
from .scoring import load_data as load_data_v4


def load_runtime_data(data_dir: Path) -> dict[str, Any]:
    if use_v5_engine():
        return load_v5_data(data_dir)
    return load_data_v4(data_dir)


def evaluate_runtime_assessment(
    answers: dict[str, str],
    data: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if data.get("version") == "v5":
        return evaluate_assessment_v5(answers, data, history=history)
    return evaluate_assessment_v4(answers, data, history=history)
