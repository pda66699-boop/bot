from __future__ import annotations

from typing import Any


def _index_level(value: int) -> str:
    if value >= 70:
        return "сильная функция"
    if value >= 50:
        return "рабочий уровень"
    if value >= 30:
        return "слабая функция"
    return "критически слабая функция"


def _dominant_function(paei: dict[str, int]) -> str:
    return max(("P", "A", "E", "I"), key=lambda key: paei.get(key, 0))


def _deficient_function(paei: dict[str, int]) -> str:
    return min(("P", "A", "E", "I"), key=lambda key: paei.get(key, 0))


def _skew_key(dominant: str, deficient: str) -> str:
    return f"{dominant}_over_{deficient}".lower()


def build_report_v5(assessment: dict[str, Any], data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    templates = data["report_templates_v5"]
    classification_type = assessment["classification_type"]
    primary_stage = assessment.get("primary_stage")
    secondary_stage = assessment.get("secondary_stage")
    title = templates["classification_titles"][classification_type]
    description = templates["classification_descriptions"][classification_type]

    stage_payload = assessment.get("report_payload") or {}
    warnings = assessment.get("warnings", [])
    warning_lines = [
        templates["warning_messages"].get(code, code)
        for code in warnings
    ]

    paei = assessment["paei"]["scores"]
    dominant = assessment["dominant_function"]
    deficient = assessment["deficient_function"]

    title_line = f"🏁 {title}: {primary_stage or 'не определена'}"
    if classification_type in {"transitional_state", "mixed_stage"} and secondary_stage:
        title_line += f" / {secondary_stage}"

    report_lines = [
        title_line,
        "",
        description,
        "",
        f"Тип классификации: {classification_type}",
        f"Уверенность: {assessment['confidence']}%",
        f"Профиль PAEI: {assessment['paei']['profile_code']}",
        "",
        "📈 Индексы PAEI",
    ]
    for letter in ("P", "A", "E", "I"):
        report_lines.append(f"- {letter}: {paei[letter]} ({_index_level(paei[letter])})")

    report_lines.extend(
        [
            "",
            f"Сильная функция: {dominant}",
            f"Слабая функция: {deficient}",
            f"Ключевой перекос: {assessment['key_skew']}",
            "",
            "Почему выбран этот результат:",
        ]
    )
    for item in assessment["explanations"]["why_this_stage"]:
        report_lines.append(f"- {item}")

    if assessment["explanations"]["why_not_prime"]:
        report_lines.extend(["", "Почему это не чистый Расцвет:"])
        for item in assessment["explanations"]["why_not_prime"]:
            report_lines.append(f"- {item}")

    if warning_lines:
        report_lines.extend(["", "⚠️ Предупреждения:"])
        for item in warning_lines:
            report_lines.append(f"- {item}")

    report_lines.extend(["", "🧭 Описание", stage_payload.get("description", description)])

    for section_key, header in (
        ("normal_problems", "🟢 Нормальные проблемы"),
        ("abnormal_problems", "🔴 Аномальные проблемы"),
        ("what_to_do", "✅ Что делать"),
        ("what_not_to_do", "⛔ Чего не делать"),
    ):
        values = stage_payload.get(section_key, [])
        report_lines.extend(["", header])
        if values:
            for item in values:
                report_lines.append(f"- {item}")
        else:
            report_lines.append("- Недостаточно данных для содержательной рекомендации.")

    report_json = {
        "title": title_line,
        "description": stage_payload.get("description", description),
        "normal_problems": stage_payload.get("normal_problems", []),
        "abnormal_problems": stage_payload.get("abnormal_problems", []),
        "what_to_do": stage_payload.get("what_to_do", []),
        "what_not_to_do": stage_payload.get("what_not_to_do", []),
    }
    return "\n".join(report_lines), report_json
