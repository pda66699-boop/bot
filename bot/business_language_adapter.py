from __future__ import annotations

from typing import Any

PAEI_CAPTIONS = {
    "P": "производство результата",
    "A": "порядок, эффективность",
    "E": "развитие, новые продукты",
    "I": "команда, коммуникации",
}

FUNCTION_NAMES = {
    "P": "результат",
    "A": "система и порядок",
    "E": "развитие",
    "I": "командное взаимодействие",
}

REQUIRED_REPLACEMENTS = {
    "не укладывается в стадию": "сейчас бизнес работает в двух режимах",
    "смешанные логики управления": "часть решений идёт через систему, часть — через ручное управление",
    "слабая функция A": "системы и порядка не хватает, чтобы удерживать результат",
    "сильная функция P": "результат тянется, но ценой перегрузки",
    "доминирующая функция": "сейчас сильнее всего выражено",
    "нормальные проблемы": "что уже мешает работать спокойно",
    "аномальные проблемы": "что станет опасным при росте",
    "result_without_system": "результат есть, но он не закреплён системой",
    "инициативы быстро затухают": "новые задачи запускаются, но не доходят до стабильного результата",
}

FORBIDDEN_LABELS = (
    "classification_type",
    "pattern",
    "family",
    "signals",
    "clusters",
    "decision_factors",
    "result_without_system",
    "growth_unstructured",
    "aging_bureaucratic",
    "prime_ready",
    "chaotic",
    "mixed",
)

DEFAULT_ACTIONS = [
    "Ввести еженедельный разбор: план -> факт -> корректировки.",
    "Зафиксировать, кто принимает решения без собственника.",
    "Привести задачи к единому формату: срок, ответственный, результат.",
    "Ограничить параллельные инициативы до 1-2 приоритетов.",
]

DEFAULT_ANTI_ACTIONS = [
    "Не запускать новые проекты, пока базовые договоренности не исполняются стабильно.",
    "Не возвращать все решения на собственника при первом сбое.",
    "Не расширять команду без закрепленных зон ответственности.",
]


def _dominant_letter(paei: dict[str, int]) -> str | None:
    values = {letter: int(paei.get(letter, 0)) for letter in ("P", "A", "E", "I")}
    sorted_values = sorted(values.items(), key=lambda item: item[1], reverse=True)
    top1 = sorted_values[0]
    top2 = sorted_values[1]
    if top1[1] - top2[1] >= 5:
        return top1[0]
    return None


def _detect_stage_hint(p: int, a: int, e: int, i: int) -> str | None:
    if p >= 60 and a < 40:
        return "Младенчество"
    if p >= 60 and a >= 50 and i >= 50:
        return "Юность"
    if a >= 60 and i >= 60 and e >= 50:
        return "Расцвет"
    if a >= 60 and e < 40:
        return "Стабильность/Аристократизм"
    return None


def _replace_required(text: str) -> str:
    updated = text
    for old, new in REQUIRED_REPLACEMENTS.items():
        updated = updated.replace(old, new)
    return updated


def _sanitize_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        line = _replace_required(line.strip())
        if not line:
            continue
        cleaned.append(line)
    return cleaned


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def normalize_result(assessment: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    paei = {letter: int(assessment["paei"]["scores"].get(letter, 0)) for letter in ("P", "A", "E", "I")}
    stage_payload = assessment.get("report_payload") or {}
    p, a, e, i = paei["P"], paei["A"], paei["E"], paei["I"]
    dominant_letter = _dominant_letter(paei)

    return {
        "classification_type": assessment.get("classification_type", "undefined"),
        "stage_name": assessment.get("primary_stage"),
        "secondary_stage": assessment.get("secondary_stage"),
        "stage_hint": _detect_stage_hint(p, a, e, i),
        "confidence": int(assessment.get("confidence", 0) or 0),
        "pattern": assessment.get("pattern", "mixed"),
        "paei": paei,
        "dominant_function": assessment.get("dominant_function"),
        "weak_function": assessment.get("deficient_function"),
        "dominant_letter": dominant_letter,
        "key_skew": assessment.get("key_skew", ""),
        "stage_payload": {
            "description": stage_payload.get("description", ""),
            "normal_problems": list(stage_payload.get("normal_problems", [])),
            "abnormal_problems": list(stage_payload.get("abnormal_problems", [])),
            "what_to_do": list(stage_payload.get("what_to_do", [])),
            "what_not_to_do": list(stage_payload.get("what_not_to_do", [])),
        },
        "templates": data.get("report_templates_v5", {}),
    }


def build_summary_title(result: dict[str, Any]) -> str:
    ct = result["classification_type"]
    weak = result.get("weak_function")
    if ct == "undefined":
        return "Сейчас бизнес держится на тебе сильнее, чем на системе"
    if ct in {"mixed_stage", "transitional_state"}:
        return "Рост есть, но он пока не закреплен управлением"
    if weak == "A":
        return "Результат есть, но системе пока не хватает опоры"
    return "Бизнес работает, но управляемость требует усиления"


def build_undefined_summary(result: dict[str, Any]) -> str:
    return (
        "Сейчас бизнес работает, но не держится одной понятной системой управления. "
        "Часть решений уже требует порядка и правил, а часть до сих пор держится на ручном управлении. "
        "Поэтому компания движется, но слишком многое снова возвращается к собственнику."
    )


def build_mixed_stage_summary(result: dict[str, Any]) -> str:
    stage_name = result.get("stage_name")
    if stage_name:
        return (
            f"Есть признаки стадии «{stage_name}», но пока не хватает управленческой цельности. "
            "Часть процессов уже собрана, а часть задач по-прежнему проходит в ручном режиме. "
            "Из-за этого система буксует и теряет скорость на росте."
        )
    return (
        "Сейчас бизнес работает в двух управленческих режимах. "
        "Одни решения проходят через систему, другие снова уходят в ручное управление. "
        "Из-за этого результат нестабилен и нагрузка возвращается к собственнику."
    )


def build_exact_stage_summary(result: dict[str, Any]) -> str:
    stage_name = result.get("stage_name")
    return (
        "Система управления уже читается достаточно цельно и предсказуемо. "
        "Бизнес держит результат, но сохраняются зоны, где управляемость проседает под нагрузкой. "
        f"Стадия «{stage_name}» здесь ориентир, а не самоцель."
    )


def build_plain_language_summary(result: dict[str, Any]) -> str:
    ct = result["classification_type"]
    if ct == "undefined":
        return build_undefined_summary(result)
    if ct in {"mixed_stage", "transitional_state"}:
        return build_mixed_stage_summary(result)
    return build_exact_stage_summary(result)


def _mirror_from_weak_function(weak_function: str | None) -> list[str]:
    by_weak = {
        "A": [
            "Одни и те же вопросы всплывают повторно и требуют твоего участия.",
            "Тебе часто проще ответить самому, чем объяснять систему решения.",
            "Руководители есть, но часть решений уходит наверх вместо исполнения на месте.",
        ],
        "P": [
            "Задачи запускаются, но не всегда доходят до результата в срок.",
            "Команда тратит больше усилий на процесс, чем на полезный выход.",
            "Сроки плывут, когда одновременно растет количество приоритетов.",
        ],
        "E": [
            "Новые задачи запускаются, но быстро теряют темп на исполнении.",
            "Рост тормозится, потому что инициатива не закрепляется в цикле управления.",
            "Решения часто закрывают текущую боль, но не двигают развитие вперед.",
        ],
        "I": [
            "Сотрудники косячат на стыках функций, когда нет общего решения.",
            "Руководители согласовывают долго и передают спорные вопросы наверх.",
            "Договоренности зависят от людей, а не от единого командного ритма.",
        ],
    }
    return by_weak.get(weak_function or "", [])


def build_business_mirror(result: dict[str, Any]) -> list[str]:
    mirror = _mirror_from_weak_function(result.get("weak_function"))
    mirror.extend(
        [
            "Как только задач становится больше, качество начинает проседать.",
            "При росте загрузки прибыль и сроки становятся менее предсказуемыми.",
        ]
    )
    stage_mirror = result["stage_payload"].get("normal_problems", [])
    mirror.extend(stage_mirror)
    return _sanitize_lines(_dedupe_keep_order(mirror))[:5]


def build_root_cause(result: dict[str, Any]) -> str:
    weak = result.get("weak_function")
    dominant = result.get("dominant_letter")

    weak_map = {
        "A": "системы и порядка не хватает, чтобы удерживать результат",
        "P": "результат в ключевых зонах проседает и не стабилизируется",
        "E": "контур развития ослаблен и новые решения затухают",
        "I": "командная связность слабая, поэтому решения теряются на стыках",
    }
    weak_text = weak_map.get(weak, "контур управления работает неравномерно")

    if dominant:
        dominant_text = FUNCTION_NAMES.get(dominant, dominant)
        line = (
            f"Сейчас сильнее всего выражено {dominant_text}, но {weak_text}. "
            "Поэтому решения не закрепляются как единая система и возвращаются в ручной режим."
        )
    else:
        line = (
            "Сейчас нет одной сильной управленческой опоры: бизнес держится сразу на нескольких режимах, "
            "но ни один не стал устойчивым."
        )

    return _replace_required(line)


def build_consequences(result: dict[str, Any]) -> list[str]:
    consequences = [
        "Деньги теряются на переделках, ошибках и лишних согласованиях.",
        "Сроки плывут, когда задачи переходят между функциями без закрепления.",
        "Нагрузка собственника растет быстрее, чем управляемость команды.",
        "Качество зависит от отдельных людей, а не от стабильного процесса.",
    ]
    consequences.extend(result["stage_payload"].get("abnormal_problems", []))
    return _sanitize_lines(_dedupe_keep_order(consequences))[:4]


def _normalize_action_verb(text: str) -> str:
    t = text.strip()
    if not t:
        return t
    t = t[0].upper() + t[1:]
    if not t.endswith("."):
        t += "."
    return t


def build_actions_now(result: dict[str, Any]) -> list[str]:
    actions = list(result["stage_payload"].get("what_to_do", []))

    if result.get("weak_function") == "A":
        actions.extend(
            [
                "Ввести единый формат постановки задач: срок, ответственный, результат.",
                "Зафиксировать зоны ответственности и уровни решений без собственника.",
                "Запустить еженедельный разбор план -> факт -> корректировки.",
            ]
        )
    else:
        actions.extend(DEFAULT_ACTIONS)

    cleaned = _sanitize_lines(_dedupe_keep_order(actions))
    cleaned = [_normalize_action_verb(item) for item in cleaned]
    return cleaned[:5]


def build_anti_actions(result: dict[str, Any]) -> list[str]:
    anti = list(result["stage_payload"].get("what_not_to_do", []))
    anti.extend(DEFAULT_ANTI_ACTIONS)
    cleaned = _sanitize_lines(_dedupe_keep_order(anti))
    cleaned = [_normalize_action_verb(item) for item in cleaned]
    return cleaned[:4]


def build_paei_compact_block(result: dict[str, Any]) -> dict[str, Any]:
    paei = result["paei"]
    lines = [f"{letter}: {paei[letter]}% — {PAEI_CAPTIONS[letter]}" for letter in ("P", "A", "E", "I")]

    return {
        "title": "📊 Профиль управления",
        "lines": lines,
        "footer": "Этот профиль показывает, за счёт чего бизнес сейчас держится, а где системе не хватает опоры.",
    }


def build_model_appendix(result: dict[str, Any]) -> str:
    ct = result["classification_type"]
    stage_name = result.get("stage_name")
    stage_hint = result.get("stage_hint")
    confidence = int(result.get("confidence", 0) or 0)

    if ct == "undefined":
        hint = f"Профиль частично напоминает стадию «{stage_hint}»." if stage_hint else ""
        return (
            "Стадия не определена осознанно. Это не ошибка и не нехватка данных. "
            "Бизнес показывает противоречивую картину управления: часть контуров уже системные, "
            "часть остаются ручными. "
            f"{hint}".strip()
        )

    if ct in {"mixed_stage", "transitional_state"}:
        right = f"Есть признаки стадии «{stage_name}». " if stage_name else ""
        return (
            f"{right}Но переход еще не завершен: сильные элементы новой модели уже есть, "
            "а часть управленческих решений пока не закреплена в системе."
        )

    confidence_line = f"Уровень уверенности в классификации: {confidence}%." if confidence > 0 else ""
    return f"Стадия «{stage_name}» используется как рабочий ориентир. {confidence_line}".strip()


def derive_business_messages(result: dict[str, Any]) -> dict[str, Any]:
    summary = build_plain_language_summary(result)
    mirror = build_business_mirror(result)
    root_cause = build_root_cause(result)
    consequences = build_consequences(result)
    actions = build_actions_now(result)
    anti_actions = build_anti_actions(result)
    paei_block = build_paei_compact_block(result)
    appendix = build_model_appendix(result)

    return {
        "classification_type": result["classification_type"],
        "stage_name": result.get("stage_name"),
        "stage_hint": result.get("stage_hint"),
        "business_title": build_summary_title(result),
        "business_summary": _replace_required(summary),
        "business_mirror": mirror,
        "root_cause": _replace_required(root_cause),
        "business_consequences": consequences,
        "actions_now": actions,
        "anti_actions": anti_actions,
        "paei_compact_block": paei_block,
        "appendix_model_text": _replace_required(appendix),
    }


def prioritize_messages(messages: dict[str, Any]) -> dict[str, Any]:
    prioritized = dict(messages)
    prioritized["business_mirror"] = messages["business_mirror"][:5]
    prioritized["business_consequences"] = messages["business_consequences"][:4]
    prioritized["actions_now"] = messages["actions_now"][:5]
    prioritized["anti_actions"] = messages["anti_actions"][:4]

    if len(prioritized["actions_now"]) < 3:
        for fallback in DEFAULT_ACTIONS:
            if fallback not in prioritized["actions_now"]:
                prioritized["actions_now"].append(fallback)
            if len(prioritized["actions_now"]) >= 3:
                break

    return prioritized


def _render_short_report(messages: dict[str, Any]) -> str:
    paei = messages["paei_compact_block"]
    lines = [
        messages["business_title"],
        "",
        messages["business_summary"],
        "",
        "Как это проявляется:",
        *(f"- {item}" for item in messages["business_mirror"][:3]),
        "",
        "Что делать первым:",
        *(f"- {item}" for item in messages["actions_now"][:3]),
        "",
        paei["title"],
        *(f"- {line}" for line in paei["lines"]),
        paei["footer"],
        "",
        f"Модельное пояснение: {messages['appendix_model_text']}",
    ]
    return "\n".join(lines)


def _render_extended_report(messages: dict[str, Any]) -> str:
    paei = messages["paei_compact_block"]
    lines = [
        messages["business_title"],
        "",
        "Краткий вывод",
        messages["business_summary"],
        "",
        "Как это выглядит у тебя в бизнесе",
        *(f"- {item}" for item in messages["business_mirror"]),
        "",
        "Микровывод: без закрепления решений нагрузка снова возвращается к собственнику.",
        "",
        "В чем корень проблемы",
        messages["root_cause"],
        "",
        "Микровывод: рост есть, но управленческий контур пока не держит его стабильно.",
        "",
        "Чем это бьет по бизнесу",
        *(f"- {item}" for item in messages["business_consequences"]),
        "",
        "Что делать сейчас",
        *(f"{idx}. {item}" for idx, item in enumerate(messages["actions_now"], start=1)),
        "",
        "Чего не делать",
        *(f"- {item}" for item in messages["anti_actions"]),
        "",
        paei["title"],
        *(f"- {line}" for line in paei["lines"]),
        paei["footer"],
        "",
        "Модельное пояснение",
        messages["appendix_model_text"],
    ]
    return "\n".join(lines)


def render_report_by_template(messages: dict[str, Any], report_mode: str = "extended_report") -> tuple[str, dict[str, Any]]:
    if report_mode == "short_report":
        report_text = _render_short_report(messages)
    else:
        report_text = _render_extended_report(messages)

    report_json = {
        "interpretation_mode": "business_language_adapted",
        "title": messages["business_title"],
        "description": messages["business_summary"],
        "business_summary": messages["business_summary"],
        "business_mirror": list(messages["business_mirror"]),
        "root_cause": messages["root_cause"],
        "business_consequences": list(messages["business_consequences"]),
        "actions_now": list(messages["actions_now"]),
        "anti_actions": list(messages["anti_actions"]),
        "paei_compact_block": dict(messages["paei_compact_block"]),
        "appendix_model_text": messages["appendix_model_text"],
        "normal_problems": list(messages["business_mirror"]),
        "abnormal_problems": list(messages["business_consequences"]),
        "what_to_do": list(messages["actions_now"]),
        "what_not_to_do": list(messages["anti_actions"]),
    }

    return report_text, report_json


def adapt_business_language(
    assessment: dict[str, Any],
    data: dict[str, Any],
    report_mode: str = "extended_report",
) -> tuple[str, dict[str, Any]]:
    normalized = normalize_result(assessment, data)
    messages = derive_business_messages(normalized)
    prioritized = prioritize_messages(messages)
    report_text, report_json = render_report_by_template(prioritized, report_mode=report_mode)

    for token in FORBIDDEN_LABELS:
        if token in report_text:
            report_text = report_text.replace(token, "")

    return report_text, report_json
