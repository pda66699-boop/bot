from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml


STAGE_ORDER = [
    "Младенчество",
    "Давай-давай",
    "Юность",
    "Ранний Расцвет",
    "Расцвет",
    "Стабильность",
    "Аристократизм",
    "Ранний бюрократизм",
    "Бюрократия",
]

AGING_STAGES = {
    "Стабильность",
    "Аристократизм",
    "Ранний бюрократизм",
    "Бюрократия",
}

DIM_ORDER = ("P", "A", "E", "I")
DEFAULT_SCORE_MAP = {"A": 3, "B": 2, "C": 1, "D": 0}


def _normalize_questions(raw_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for q in raw_questions:
        options_raw = q.get("options", {})
        if isinstance(options_raw, dict):
            options = [{"key": key, "label": str(label)} for key, label in options_raw.items()]
        else:
            options = options_raw

        normalized.append(
            {
                "id": q["id"],
                "dim": q.get("dim") or q.get("dimension", ""),
                "text": q["text"],
                "options": options,
                "score": q.get("score", DEFAULT_SCORE_MAP),
                "flags": q.get("flags", {"inversion": False, "stage_signals": []}),
            }
        )
    return normalized


def _normalize_stages(raw_stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for st in raw_stages:
        item = dict(st)
        if "name" not in item and "id" in item:
            item["name"] = item["id"]
        stages.append(item)
    return stages


def _stage_map_from_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    raw_stages = loaded.get("stages")
    if isinstance(raw_stages, list):
        return _normalize_stages(raw_stages)
    return []


def _merge_stage_content(primary: list[dict[str, Any]], fallback_maps: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    content_fields = (
        "description",
        "risks",
        "normal_problems",
        "anomalous_problems",
        "next_actions_base",
        "actions_by_deficit",
        "dont",
    )
    fallback_by_name: list[dict[str, dict[str, Any]]] = []
    for stages in fallback_maps:
        fallback_by_name.append({s["name"]: s for s in stages})

    merged: list[dict[str, Any]] = []
    for stage in primary:
        out = dict(stage)
        for field in content_fields:
            has_value = field in out and out[field] not in (None, [], {}, "")
            if has_value:
                continue
            for mp in fallback_by_name:
                src = mp.get(out["name"])
                if not src:
                    continue
                src_val = src.get(field)
                if src_val not in (None, [], {}, ""):
                    out[field] = src_val
                    break
        merged.append(out)
    return merged


def load_data(data_dir: Path) -> dict[str, Any]:
    stage_map_v4_path = data_dir / "stage_map_v4.yaml"
    stage_map_v3_path = data_dir / "stage_map_v3.yaml"
    stage_map_v2_path = data_dir / "stage_map_v2.yaml"
    legacy_stages_path = data_dir / "stages.yaml"
    questions_v2_path = data_dir / "questions_v2.yaml"
    questions_legacy_path = data_dir / "questions.json"
    report_templates_v4_path = data_dir / "report_templates_v4.yaml"
    report_templates_v3_path = data_dir / "report_templates_v3.yaml"
    report_templates_v2_path = data_dir / "report_templates_v2.yaml"

    if stage_map_v4_path.exists():
        with stage_map_v4_path.open("r", encoding="utf-8") as f:
            stage_map = yaml.safe_load(f)
        stages = _normalize_stages(stage_map["stages"])
        fallbacks: list[list[dict[str, Any]]] = []
        if stage_map_v3_path.exists():
            fallbacks.append(_stage_map_from_file(stage_map_v3_path))
        if stage_map_v2_path.exists():
            fallbacks.append(_stage_map_from_file(stage_map_v2_path))
        if legacy_stages_path.exists():
            fallbacks.append(_stage_map_from_file(legacy_stages_path))
        stages = _merge_stage_content(stages, fallbacks)
        scoring_config = stage_map.get("config", {})
    elif stage_map_v3_path.exists():
        with stage_map_v3_path.open("r", encoding="utf-8") as f:
            stage_map = yaml.safe_load(f)
        stages = _normalize_stages(stage_map["stages"])
        scoring_config = stage_map.get("config", {})
    elif stage_map_v2_path.exists():
        with stage_map_v2_path.open("r", encoding="utf-8") as f:
            stage_map = yaml.safe_load(f)
        stages = _normalize_stages(stage_map["stages"])
        scoring_config = stage_map.get("config", {})
    else:
        with legacy_stages_path.open("r", encoding="utf-8") as f:
            stages = _normalize_stages(yaml.safe_load(f)["stages"])
        scoring_config = {}

    with (data_dir / "dimensions.yaml").open("r", encoding="utf-8") as f:
        dimensions = yaml.safe_load(f)["dimensions"]

    if questions_v2_path.exists():
        with questions_v2_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        questions = _normalize_questions(loaded["questions"])
    else:
        with questions_legacy_path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        questions = _normalize_questions(loaded)

    report_templates: dict[str, Any] = {}
    if report_templates_v4_path.exists():
        with report_templates_v4_path.open("r", encoding="utf-8") as f:
            report_templates = yaml.safe_load(f) or {}
    elif report_templates_v3_path.exists():
        with report_templates_v3_path.open("r", encoding="utf-8") as f:
            report_templates = yaml.safe_load(f) or {}
    elif report_templates_v2_path.exists():
        with report_templates_v2_path.open("r", encoding="utf-8") as f:
            report_templates = yaml.safe_load(f) or {}

    stage_by_name = {s["name"]: s for s in stages}
    questions_by_id = {q["id"]: q for q in questions}

    return {
        "stages": stages,
        "stage_by_name": stage_by_name,
        "dimensions": dimensions,
        "questions": questions,
        "questions_by_id": questions_by_id,
        "report_templates": report_templates,
        "scoring_config": scoring_config,
    }


def _answer_points(question: dict[str, Any], answer_key: str) -> int:
    score_map = question.get("score", DEFAULT_SCORE_MAP)
    raw = int(score_map.get(answer_key, 0))
    inversion = bool(question.get("flags", {}).get("inversion", False))
    return 3 - raw if inversion else raw


def calculate_indices(answers: dict[str, str], questions_by_id: dict[str, dict[str, Any]]) -> dict[str, int]:
    sums = {dim: 0 for dim in DIM_ORDER}
    for qid, answer_key in answers.items():
        question = questions_by_id.get(qid)
        if not question:
            continue
        dim = question.get("dim", "")
        if dim in sums:
            sums[dim] += _answer_points(question, answer_key)
    max_points = 18
    return {dim: round(sums[dim] / max_points * 100) for dim in DIM_ORDER}


def _idx_symbol(letter: str, idx: int) -> str:
    if idx >= 70:
        return letter.upper()
    else:
        return letter.lower()


def build_profile_code(indices: dict[str, int]) -> str:
    return "".join(_idx_symbol(letter, indices.get(letter, 0)) for letter in DIM_ORDER)


def _euclidean_distance(v1: dict[str, int], v2: dict[str, int]) -> float:
    return math.sqrt(sum((v1[dim] - v2[dim]) ** 2 for dim in DIM_ORDER))


def _passes_rule(value: int, rule: dict[str, int]) -> bool:
    min_ok = value >= int(rule["min"]) if "min" in rule else True
    max_ok = value <= int(rule["max"]) if "max" in rule else True
    return min_ok and max_ok


def _is_stage_admissible(indices: dict[str, int], stage: dict[str, Any]) -> bool:
    admissibility = stage.get("admissibility", {}) or {}
    return all(_passes_rule(indices[dim], rule) for dim, rule in admissibility.items() if dim in indices)


def _stage_target_distance(indices: dict[str, int], stage: dict[str, Any]) -> float:
    if "targets" in stage:
        targets = stage.get("targets", [])
        if not targets:
            return float("inf")
        return min(_euclidean_distance(indices, {d: int(target[d]) for d in DIM_ORDER}) for target in targets)
    target = stage.get("target")
    if not target:
        return float("inf")
    return _euclidean_distance(indices, {d: int(target[d]) for d in DIM_ORDER})


def _stage_distances(indices: dict[str, int], stages: list[dict[str, Any]]) -> dict[str, float]:
    return {stage["name"]: _stage_target_distance(indices, stage) for stage in stages}


def _fallback_admissible(indices: dict[str, int], stages: list[dict[str, Any]]) -> list[str]:
    relaxed: list[str] = []
    for stage in stages:
        name = stage["name"]
        rules = stage.get("admissibility", {}) or {}
        failures = 0
        blocked = False
        for dim, rule in rules.items():
            if dim not in indices:
                continue
            if _passes_rule(indices[dim], rule):
                continue
            failures += 1
            if name == "Стабильность" and dim == "E" and "max" in rule:
                blocked = True
                break
        if not blocked and failures == 1:
            relaxed.append(name)
    return relaxed


def _calc_regress(
    stage: str,
    confidence: int,
    stage_order: dict[str, int],
    history: list[dict[str, Any]] | None,
    conf_min: int,
) -> tuple[bool, bool]:
    if not history or len(history) < 3:
        return False, False
    if confidence <= conf_min:
        return False, False

    prev = history[0]
    prev_stage = str(prev.get("stage", "")).strip()
    prev_conf = int(prev.get("confidence", 0) or 0)
    if not prev_stage or prev_stage not in stage_order:
        return False, False
    if prev_conf <= conf_min:
        return False, False

    # Special rule: Stability -> Prime is recovery, not regress.
    if prev_stage == "Стабильность" and stage == "Расцвет":
        return False, True

    return stage_order[stage] < stage_order[prev_stage], False


def determine_stage(
    indices: dict[str, int],
    stages: list[dict[str, Any]],
    scoring_config: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = scoring_config or {}
    transition_delta = float(config.get("transition_delta", 7))
    hybrid_delta = float(config.get("hybrid_delta", 5))
    regress_confidence_min = int(config.get("regress_confidence_min", 70))

    distances = _stage_distances(indices, stages)
    stage_order = {stage["name"]: int(stage.get("order", idx + 1)) for idx, stage in enumerate(stages)}

    admissible = [stage["name"] for stage in stages if _is_stage_admissible(indices, stage)]
    no_admissible_stage = len(admissible) == 0

    ranked_all = sorted(((name, distances[name]) for name in stage_order), key=lambda x: x[1])
    candidates_top_n = int(config.get("candidates_top_n", 3))
    candidates = [
        {"stage": name, "distance": round(distance, 3)}
        for name, distance in ranked_all[: max(candidates_top_n, 1)]
    ]

    if no_admissible_stage:
        ranked = sorted(((name, distances[name]) for name in stage_order), key=lambda x: x[1])
    else:
        ranked = sorted(((name, distances[name]) for name in admissible), key=lambda x: x[1])

    best_stage, best_distance = ranked[0]
    second_stage, second_distance = (ranked[1] if len(ranked) > 1 else (best_stage, best_distance))

    has_second = len(ranked) > 1 and second_stage != best_stage
    adjacent = has_second and abs(stage_order[best_stage] - stage_order[second_stage]) == 1
    distance_gap = (second_distance - best_distance) if has_second else float("inf")

    transition = None
    hybrid = False

    confidence = 100
    if has_second and (best_distance + second_distance) > 0:
        confidence = round(100 * (second_distance / (best_distance + second_distance)))

    if no_admissible_stage:
        # Fallback mode: profile does not fit any admissible stage.
        hybrid = True
        transition = None
        confidence = min(confidence, 50)
        regress = False
        recovery = False
    else:
        if has_second and adjacent and distance_gap <= transition_delta:
            transition = f'Переход от "{second_stage}" к "{best_stage}"'
        elif has_second and (not adjacent) and distance_gap <= hybrid_delta:
            transition = f'Гибридный профиль: "{best_stage}" + "{second_stage}"'
            hybrid = True

        regress, recovery = _calc_regress(
            stage=best_stage,
            confidence=confidence,
            stage_order=stage_order,
            history=history,
            conf_min=regress_confidence_min,
        )

    return {
        "stage": best_stage,
        "second_best_stage": second_stage,
        "nearest_stage": second_stage,
        "second_stage": second_stage,
        "distance": round(best_distance, 3),
        "distance_gap": round(distance_gap, 3) if math.isfinite(distance_gap) else float("inf"),
        "transition": transition,
        "hybrid": hybrid,
        "confidence": confidence,
        "regress": regress,
        "recovery": recovery,
        "no_admissible_stage": no_admissible_stage,
        "admissible_stages": admissible,
        "candidates": candidates,
        "distances": {k: round(v, 3) for k, v in distances.items()},
    }


def _dominant_letters(indices: dict[str, int]) -> list[str]:
    return [k for k, v in indices.items() if v >= 70]


def _deficit_letters(indices: dict[str, int]) -> list[str]:
    return [k for k, v in indices.items() if v < 50]


def _profile_meaning(indices: dict[str, int]) -> str:
    dominant = _dominant_letters(indices)
    deficits = _deficit_letters(indices)

    dom_text = ", ".join(dominant) if dominant else "нет выраженных"
    if deficits:
        def_text = ", ".join(deficits)
    else:
        def_text = "нет"

    return f"Доминирующие контуры: {dom_text}. Зоны дефицита: {def_text}."


def _pad_risks(risks: list[str], report_templates: dict[str, Any]) -> list[str]:
    cfg = report_templates.get("report", {})
    risk_count = int(cfg.get("risk_count", 5))
    extra = list(report_templates.get("defaults", {}).get("extra_risks", []))
    out = list(risks)
    while len(out) < risk_count and extra:
        out.append(extra.pop(0))
    return out[:risk_count]


def _build_actions(stage_payload: dict[str, Any], indices: dict[str, int], report_templates: dict[str, Any]) -> list[str]:
    max_count = int(report_templates.get("report", {}).get("actions_max", 5))
    actions = list(stage_payload.get("do", []))
    priorities = report_templates.get("deficit_priorities", {})
    deficits = _deficit_letters(indices)
    prioritized: list[str] = []
    for letter in deficits:
        prioritized.extend(priorities.get(letter, []))
    actions = prioritized[:2] + actions

    out: list[str] = []
    seen: set[str] = set()
    for item in actions:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= max_count:
            break
    return out


def _unique_limit(items: list[str], limit: int, placeholder: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    if not out:
        return [placeholder]
    return out


def _fallback_sections(indices: dict[str, int], report_templates: dict[str, Any]) -> dict[str, list[str]]:
    report_cfg = report_templates.get("report", {})
    defaults = report_templates.get("defaults", {})
    library = report_templates.get("deficit_library", {})
    threshold = int(report_cfg.get("fallback_deficit_threshold", 60))
    max_problems = int(report_cfg.get("problems_count", 5))
    max_actions = int(report_cfg.get("actions_max", 5))
    max_dont = int(report_cfg.get("dont_max", 5))
    placeholder = defaults.get("normal_problems_placeholder", "-")

    deficits = [letter for letter, value in indices.items() if value < threshold]
    deficits = sorted(deficits, key=lambda letter: indices[letter])

    normal: list[str] = []
    abnormal: list[str] = []
    actions: list[str] = []
    dont: list[str] = []
    for letter in deficits:
        payload = library.get(letter, {})
        normal.extend(payload.get("normal_problems", []))
        abnormal.extend(payload.get("abnormal_problems", []))
        actions.extend(payload.get("do", []))
        dont.extend(payload.get("dont", []))

    actions.extend((report_templates.get("fallback", {}) or {}).get("general_do", []))
    dont.extend((report_templates.get("fallback", {}) or {}).get("general_dont", []))

    return {
        "normal": _unique_limit(normal, max_problems, placeholder),
        "abnormal": _unique_limit(abnormal, max_problems, placeholder),
        "actions": _unique_limit(actions, max_actions, placeholder),
        "dont": _unique_limit(dont, max_dont, placeholder),
    }


def _index_dimension_meaning(letter: str) -> str:
    return {
        "P": "результат и клиент",
        "A": "система и порядок",
        "E": "развитие и возможности",
        "I": "команда и согласованность",
    }[letter]


def _index_level(value: int) -> str:
    if value >= 70:
        return "сильная функция"
    if value >= 50:
        return "средний уровень"
    if value >= 30:
        return "слабая функция"
    return "критически слабая функция"


def _index_interpretation(indices: dict[str, int]) -> tuple[str, str, str, str]:
    strongest = max(DIM_ORDER, key=lambda dim: indices.get(dim, 0))
    weakest = min(DIM_ORDER, key=lambda dim: indices.get(dim, 0))
    strongest_line = f"Сильная функция: {strongest} — {_index_dimension_meaning(strongest)}"
    weakest_line = f"Слабая функция: {weakest} — {_index_dimension_meaning(weakest)}"
    return strongest, weakest, strongest_line, weakest_line


def _culture_type(profile_code: str) -> str:
    mapping = {
        "paeI": "командно-хаотичная культура",
        "PaEi": "предпринимательская культура",
        "pAEi": "управленческий переход",
        "PAEI": "сбалансированная культура",
        "pAei": "бюрократизирующаяся культура",
    }
    return mapping.get(profile_code, "смешанный тип управленческой культуры")


def _main_management_problem(min_function: str, min_value: int) -> str:
    if min_value >= 70:
        return "Критичной управленческой проблемы не выявлено: функции управления развиты сбалансированно."
    messages = {
        "A": "компания масштабирует результат без устойчивой системы управления.",
        "E": "организация теряет предпринимательскую энергию и способность к обновлению.",
        "P": "организация теряет фокус на результате и клиентской ценности.",
        "I": "команда и подразделения работают несогласованно.",
    }
    return messages[min_function]


def build_report(
    indices: dict[str, int],
    profile_code: str,
    stage_result: dict[str, Any],
    stage: dict[str, Any],
    report_templates: dict[str, Any],
) -> str:
    defaults = report_templates.get("defaults", {})
    report_cfg = report_templates.get("report", {})
    no_admissible_stage = bool(stage_result.get("no_admissible_stage"))

    header = f"🏁 Текущая модель развития: ближе всего к стадии «{stage['name']}»"

    stage_tpl = (report_templates.get("stages", {}) or {}).get(stage["name"], {})
    risks = _pad_risks(list(stage_tpl.get("risks", stage.get("risks", []))), report_templates)
    if no_admissible_stage:
        fallback = _fallback_sections(indices, report_templates)
        normal = fallback["normal"]
        anomalous = fallback["abnormal"]
        actions = fallback["actions"]
        dont = fallback["dont"]
    else:
        normal = list(stage_tpl.get("normal_problems", stage.get("normal_problems", [])))[: int(report_cfg.get("problems_count", 5))]
        anomalous = list(stage_tpl.get("abnormal_problems", stage.get("anomalous_problems", [])))[: int(report_cfg.get("problems_count", 5))]
        if not normal:
            normal = [defaults.get("normal_problems_placeholder", "-")]
        if not anomalous:
            anomalous = [defaults.get("normal_problems_placeholder", "-")]

        actions = _build_actions(stage_tpl if stage_tpl else stage, indices, report_templates)
        if not actions:
            actions = [defaults.get("normal_problems_placeholder", "-")]

        dont = list(stage_tpl.get("dont", stage.get("dont", [])))
        dont_by_deficit = defaults.get("dont_by_deficit", {})
        for letter in _deficit_letters(indices):
            dont.extend(dont_by_deficit.get(letter, [])[:1])
        dont = dont[: int(report_cfg.get("dont_max", 5))] or [defaults.get("normal_problems_placeholder", "-")]

    description = stage_tpl.get("description_base", stage.get("description", _profile_meaning(indices)))
    strongest, weakest, strongest_line, weakest_line = _index_interpretation(indices)
    strong_company = min(indices.values()) >= 70
    second_best_stage = stage_result.get("second_best_stage", stage["name"])
    second_best_line = (
        f"Также компания показывает признаки стадии: {second_best_stage}\n\n"
        if second_best_stage and second_best_stage != stage["name"]
        else ""
    )
    fallback_note = ""
    if no_admissible_stage:
        fallback_note = (
            "📌 Сейчас профиль компании сочетает признаки нескольких стадий,\n"
            "поэтому результат показывает наиболее близкую модель развития.\n\n"
            "⚠️ Ваша компания показывает смешанные признаки разных стадий развития.\n"
            "Это часто происходит в периоды роста или управленческих изменений.\n\n"
            "Поэтому ниже приведена модель, которая сейчас наиболее похожа на вашу ситуацию,\n"
            "и рекомендации по усилению ключевых управленческих функций.\n\n"
        )

    parts = [
        f"{header}\n\n",
        fallback_note,
        second_best_line,
        f"Профиль управления (PAEI): {profile_code}\n\n",
        "P — результат и клиент\n",
        "A — система и порядок\n",
        "E — развитие и возможности\n",
        "I — команда и согласованность\n\n",
        "📈 Индексы (0-100)\n",
        f"- P — результат и клиент: {indices['P']} ({_index_level(indices['P'])})\n",
        f"- A — система и порядок: {indices['A']} ({_index_level(indices['A'])})\n",
        f"- E — развитие и возможности: {indices['E']} ({_index_level(indices['E'])})\n",
        f"- I — команда и согласованность: {indices['I']} ({_index_level(indices['I'])})\n\n",
        "📊 Что показывают индексы\n",
        f"Самая сильная сторона: {strongest} — {_index_dimension_meaning(strongest)}\n",
        (
            "Самая слабая функция: не выявлена\n"
            if strong_company
            else f"Самая слабая функция: {weakest} — {_index_dimension_meaning(weakest)}\n"
        ),
        "\n",
        "📌 Главный управленческий перекос\n",
        f"{strongest_line}\n",
        (
            "Все управленческие функции развиты на высоком уровне.\n"
            "Явных слабых функций не выявлено.\n\n"
            if strong_company
            else (
                f"{weakest_line}\n\n"
                f"Компания демонстрирует перекос управления:\nсильная {strongest} при слабой {weakest}.\n\n"
            )
        ),
        f"Тип управленческой культуры: {_culture_type(profile_code)}\n\n",
        f"🧭 Описание стадии\n{description}\n{_profile_meaning(indices)}\n\n",
        "⚠️ Ключевые риски\n",
        "\n".join(f"- {x}" for x in risks),
        "\n\n",
        "🟢 Нормальные проблемы\n",
        "\n".join(f"- {x}" for x in normal),
        "\n\n",
        "🔴 Аномальные проблемы\n",
        "\n".join(f"- {x}" for x in anomalous),
        "\n\n",
        "📌 Главная управленческая проблема\n",
        f"{_main_management_problem(weakest, indices[weakest])}\n\n",
        "✅ Что делать\n",
        "\n".join(f"- {x}" for x in actions),
        "\n\n",
        "⛔ Чего не делать\n",
        "\n".join(f"- {x}" for x in dont),
    ]
    return "".join(parts)


def evaluate_assessment(
    answers: dict[str, str],
    data: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    indices = calculate_indices(answers, data["questions_by_id"])
    profile_code = build_profile_code(indices)
    stage_result = determine_stage(
        indices=indices,
        stages=data["stages"],
        scoring_config=data.get("scoring_config", {}),
        history=history,
    )
    stage = data["stage_by_name"][stage_result["stage"]]
    warnings: list[str] = []
    if stage_result.get("no_admissible_stage"):
        warnings.append("no_admissible_stage")
        warnings.append("low_confidence")
        if stage_result.get("distance_gap", float("inf")) <= float(data.get("scoring_config", {}).get("transition_delta", 7)):
            warnings.append("near_boundary")
    if stage_result["confidence"] < 60:
        if "low_confidence" not in warnings:
            warnings.append("low_confidence")
    if stage_result.get("transition") or stage_result.get("hybrid"):
        if "near_boundary" not in warnings:
            warnings.append("near_boundary")
    if history and any(not str(h.get("run_id", "")).strip() for h in history):
        warnings.append("history_migrated_or_inconsistent")
    if stage_result.get("recovery"):
        warnings.append("recovery_detected")

    report_text = build_report(
        indices=indices,
        profile_code=profile_code,
        stage_result=stage_result,
        stage=stage,
        report_templates=data.get("report_templates", {}),
    )

    return {
        "indices": indices,
        "profile_code": profile_code,
        "stage": stage_result["stage"],
        "second_best_stage": stage_result["second_best_stage"],
        "nearest_stage": stage_result["nearest_stage"],
        "second_stage": stage_result["second_stage"],
        "transition": stage_result["transition"],
        "hybrid": stage_result["hybrid"],
        "confidence": stage_result["confidence"],
        "regress": stage_result["regress"],
        "warnings": warnings,
        "distance": stage_result["distance"],
        "distance_gap": stage_result["distance_gap"],
        "admissible_stages": stage_result["admissible_stages"],
        "candidates": stage_result["candidates"],
        "distances": stage_result["distances"],
        "report_text": report_text,
        "normal_problems": (data.get("report_templates", {}).get("stages", {}).get(stage["name"], {}).get("normal_problems", stage.get("normal_problems", []))),
        "abnormal_problems": (data.get("report_templates", {}).get("stages", {}).get(stage["name"], {}).get("abnormal_problems", stage.get("anomalous_problems", []))),
        "recommendations": (data.get("report_templates", {}).get("stages", {}).get(stage["name"], {}).get("do", stage.get("next_actions_base", []))),
    }
