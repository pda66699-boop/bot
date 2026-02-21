from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


STAGE_ORDER = [
    "Младенчество",
    "Давай-давай",
    "Юность",
    "Расцвет",
    "Стабильность",
    "Аристократизм",
    "Ранний бюрократизм",
    "Бюрократия",
]


def load_data(data_dir: Path) -> dict[str, Any]:
    with (data_dir / "stages.yaml").open("r", encoding="utf-8") as f:
        stages = yaml.safe_load(f)["stages"]
    with (data_dir / "dimensions.yaml").open("r", encoding="utf-8") as f:
        dimensions = yaml.safe_load(f)["dimensions"]
    with (data_dir / "questions.json").open("r", encoding="utf-8") as f:
        questions = json.load(f)

    stage_by_name = {s["name"]: s for s in stages}
    questions_by_id = {q["id"]: q for q in questions}
    return {
        "stages": stages,
        "stage_by_name": stage_by_name,
        "dimensions": dimensions,
        "questions": questions,
        "questions_by_id": questions_by_id,
    }


def _selected_option(question: dict[str, Any], key: str) -> dict[str, Any]:
    for option in question["options"]:
        if option["key"] == key:
            return option
    raise KeyError(f"Option {key} not found for {question['id']}")


def calculate_stage_scores(
    answers: dict[str, str],
    questions_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    totals = {stage: 0 for stage in STAGE_ORDER}
    for qid, key in answers.items():
        question = questions_by_id[qid]
        option = _selected_option(question, key)
        for stage in STAGE_ORDER:
            totals[stage] += int(option["scores"].get(stage, 0))
    return totals


def _kpi_contour_stage_points(
    stage: str,
    answers: dict[str, str],
    questions_by_id: dict[str, dict[str, Any]],
) -> int:
    total = 0
    for qid in ("Q10", "Q11", "Q12"):
        key = answers.get(qid)
        if not key:
            continue
        option = _selected_option(questions_by_id[qid], key)
        total += int(option["scores"].get(stage, 0))
    return total


def select_winner(
    stage_scores: dict[str, int],
    answers: dict[str, str],
    questions_by_id: dict[str, dict[str, Any]],
) -> tuple[str, int, int]:
    sorted_scores = sorted(stage_scores.items(), key=lambda x: x[1], reverse=True)
    winner_name, winner_score = sorted_scores[0]
    runner_up_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0

    tied = [name for name, score in stage_scores.items() if score == winner_score]
    if len(tied) == 1:
        return winner_name, winner_score, runner_up_score

    tied = sorted(
        tied,
        key=lambda s: _kpi_contour_stage_points(s, answers, questions_by_id),
        reverse=True,
    )
    top_kpi = _kpi_contour_stage_points(tied[0], answers, questions_by_id)
    kpi_tied = [s for s in tied if _kpi_contour_stage_points(s, answers, questions_by_id) == top_kpi]
    if len(kpi_tied) == 1:
        return kpi_tied[0], winner_score, runner_up_score

    weighted_sum = 0.0
    total = sum(stage_scores.values())
    if total > 0:
        for i, stage in enumerate(STAGE_ORDER, start=1):
            weighted_sum += stage_scores[stage] * i
        center = weighted_sum / total
    else:
        center = 1.0

    kpi_tied.sort(key=lambda s: (abs((STAGE_ORDER.index(s) + 1) - center), STAGE_ORDER.index(s)))
    return kpi_tied[0], winner_score, runner_up_score


def calculate_confidence(winner_score: int, runner_up_score: int, total_sum: int) -> int:
    margin = winner_score - runner_up_score
    part_margin = 0.7 * (margin / max(winner_score, 1))
    part_weight = 0.3 * (winner_score / max(total_sum, 1))
    confidence = round(100 * (part_margin + part_weight))
    return max(0, min(100, confidence))


def _index_score(answers: dict[str, str], question_ids: tuple[str, ...], mapping: dict[str, int]) -> int:
    total = 0
    for qid in question_ids:
        total += mapping.get(answers.get(qid, ""), 0)
    return round(100 * total / (len(question_ids) * 3))


def calculate_indices(answers: dict[str, str]) -> dict[str, int]:
    return {
        "owner_dependency": _index_score(
            answers,
            ("Q07", "Q08", "Q09"),
            {"A": 3, "B": 2, "C": 1, "D": 0},
        ),
        "process_formalization": _index_score(
            answers,
            ("Q04", "Q05", "Q06"),
            {"A": 0, "B": 1, "C": 2, "D": 3},
        ),
        "management_contour": _index_score(
            answers,
            ("Q10", "Q11", "Q12"),
            {"A": 0, "B": 1, "C": 3, "D": 1},
        ),
    }
