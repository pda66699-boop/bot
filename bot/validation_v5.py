from __future__ import annotations

from typing import Any


def validate_answers(answers: dict[str, str], question_bank: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    answered_required = 0
    total_required = 0

    for question_id, answer_key in answers.items():
        question = question_bank.get(question_id)
        if not question:
            errors.append({"type": "unknown_question", "question_id": question_id})
            continue
        if answer_key not in question["options_map"]:
            errors.append(
                {
                    "type": "invalid_answer",
                    "question_id": question_id,
                    "answer": answer_key,
                }
            )

    for question in question_bank.values():
        if not question.get("required", True):
            continue
        total_required += 1
        if question["id"] in answers and answers[question["id"]] in question["options_map"]:
            answered_required += 1

    completeness = answered_required / total_required if total_required else 1.0
    status = "ok"
    if any(error["type"] in {"unknown_question", "invalid_answer"} for error in errors):
        status = "invalid"
    elif completeness < 1.0:
        status = "incomplete"

    return {
        "status": status,
        "errors": errors,
        "completeness": completeness,
    }
