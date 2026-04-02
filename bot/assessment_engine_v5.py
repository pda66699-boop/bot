from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from .validation_v5 import validate_answers
from .report_builder_v5 import build_report_v5


DIMENSIONS = ("P", "A", "E", "I")
CLASSIFICATION_ORDER = ("exact_stage", "transitional_state", "mixed_stage", "undefined")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize_questions_v5(raw_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for raw in raw_questions:
        options_map = raw.get("options", {})
        options = [{"key": key, "label": payload["text"]} for key, payload in options_map.items()]
        questions.append(
            {
                "id": raw["id"],
                "text": raw["text"],
                "dim": raw["dimension"],
                "dimension": raw["dimension"],
                "weight": float(raw.get("weight", 1.0)),
                "required": bool(raw.get("required", True)),
                "options": options,
                "options_map": options_map,
            }
        )
    return questions


def load_v5_data(data_dir: Path) -> dict[str, Any]:
    with (data_dir / "questions_v3.yaml").open("r", encoding="utf-8") as file:
        raw_questions = yaml.safe_load(file)["questions"]
    with (data_dir / "traits.yaml").open("r", encoding="utf-8") as file:
        traits = yaml.safe_load(file)["traits"]
    with (data_dir / "stage_definitions_v5.yaml").open("r", encoding="utf-8") as file:
        stage_payload = yaml.safe_load(file)
    with (data_dir / "report_templates_v5.yaml").open("r", encoding="utf-8") as file:
        report_templates = yaml.safe_load(file)

    questions = _normalize_questions_v5(raw_questions)
    questions_by_id = {question["id"]: question for question in questions}
    stages = stage_payload["stages"]
    stage_by_name = {stage["label"]: stage for stage in stages}
    stage_by_name["Не определено"] = {
        "id": "undefined",
        "label": "Не определено",
        "order": 0,
        "family": "undefined",
        "normal_problems": [],
        "abnormal_problems": [],
        "what_to_do": [],
        "what_not_to_do": [],
    }

    return {
        "version": "v5",
        "questions": questions,
        "questions_by_id": questions_by_id,
        "traits": traits,
        "stages": stages,
        "stage_by_name": stage_by_name,
        "stage_config": stage_payload.get("config", {}),
        "report_templates_v5": report_templates,
    }


def _normalize_dimension(raw_value: float, raw_max: float) -> int:
    if raw_max <= 0:
        return 0
    return round(_clamp(raw_value / raw_max) * 100)


def _normalize_trait_value(raw_value: float, raw_max: float) -> float:
    if raw_max <= 0:
        return 0.0
    return _clamp(raw_value / raw_max)


def _profile_code(indices: dict[str, int]) -> str:
    return "".join(letter if indices[letter] >= 70 else letter.lower() for letter in DIMENSIONS)


def _skew_key(dominant: str, deficient: str) -> str:
    mapping = {
        ("I", "E"): "integration_without_entrepreneurial_drive",
        ("A", "E"): "administration_over_entrepreneurship",
        ("P", "A"): "result_without_system",
        ("E", "I"): "entrepreneurial_push_without_integration",
    }
    return mapping.get((dominant, deficient), f"{dominant.lower()}_over_{deficient.lower()}")


def _score_raw(answers: dict[str, str], question_bank: dict[str, dict[str, Any]]) -> tuple[dict[str, int], dict[str, float], dict[str, float]]:
    paei_raw = {dim: 0.0 for dim in DIMENSIONS}
    paei_max = {dim: 0.0 for dim in DIMENSIONS}
    traits_raw: dict[str, float] = defaultdict(float)
    traits_max: dict[str, float] = defaultdict(float)
    signals_raw: dict[str, float] = defaultdict(float)

    for question_id, answer_key in answers.items():
        question = question_bank.get(question_id)
        if not question:
            continue
        option = question["options_map"].get(answer_key)
        if not option:
            continue
        weight = float(question.get("weight", 1.0))
        for dim, value in option.get("paei", {}).items():
            paei_raw[dim] += float(value) * weight
            paei_max[dim] += 3.0 * weight
        for trait_name, value in option.get("traits", {}).items():
            traits_raw[trait_name] += float(value) * weight
            traits_max[trait_name] += 2.0 * weight
        for signal_name, value in option.get("stage_signals", {}).items():
            signals_raw[signal_name] += float(value) * weight

    paei_norm = {dim: _normalize_dimension(paei_raw[dim], paei_max[dim]) for dim in DIMENSIONS}
    traits_norm = {
        trait_name: _normalize_trait_value(raw_value, traits_max.get(trait_name, 0.0))
        for trait_name, raw_value in traits_raw.items()
    }
    if signals_raw:
        max_abs = max(abs(value) for value in signals_raw.values()) or 1.0
        signals_norm = {name: value / max_abs for name, value in signals_raw.items()}
    else:
        signals_norm = {}
    return paei_norm, traits_norm, signals_norm


def _aggregate_clusters(traits: dict[str, float], trait_defs: dict[str, Any]) -> dict[str, float]:
    cluster_scores: dict[str, float] = defaultdict(float)
    cluster_weights: dict[str, float] = defaultdict(float)
    for trait_name, raw_value in traits.items():
        trait_def = trait_defs.get(trait_name)
        if not trait_def:
            continue
        cluster = trait_def["cluster"]
        weight = float(trait_def.get("weight", 1.0))
        cluster_scores[cluster] += raw_value * weight
        cluster_weights[cluster] += weight

    clusters = {}
    for cluster_name in (
        "execution",
        "administration",
        "entrepreneurship",
        "integration",
        "aging",
        "immaturity",
    ):
        score = cluster_scores.get(cluster_name, 0.0)
        weight = cluster_weights.get(cluster_name, 0.0)
        clusters[cluster_name] = _clamp(score / weight) if weight else 0.0
    return clusters


def _check_gate(gate: dict[str, Any], clusters: dict[str, float], traits: dict[str, float], signals: dict[str, float]) -> bool:
    gate_type = gate["type"]
    if gate_type.startswith("cluster_"):
        value = clusters.get(gate["cluster"], 0.0)
    elif gate_type.startswith("trait_"):
        value = traits.get(gate["trait"], 0.0)
    elif gate_type.startswith("signal_"):
        value = signals.get(gate["signal"], 0.0)
    else:
        return False

    if gate_type.endswith("_min"):
        return value >= float(gate["value"])
    if gate_type.endswith("_max"):
        return value <= float(gate["value"])
    if gate_type.endswith("_range"):
        return float(gate["min"]) <= value <= float(gate["max"])
    return False


def _weighted_match(expected: dict[str, float], traits: dict[str, float], signals: dict[str, float]) -> float:
    if not expected:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for key, weight in expected.items():
        base_key = str(key)
        expected_weight = float(weight)
        actual = traits.get(base_key)
        if actual is None:
            actual = signals.get(base_key)
        if actual is None and base_key.endswith("_signal"):
            actual = signals.get(base_key)
        if actual is None and not base_key.endswith("_signal"):
            actual = signals.get(base_key)
        if actual is None:
            actual = 0.0

        if expected_weight >= 0:
            contribution = _clamp(actual)
            denominator += expected_weight
            numerator += expected_weight * contribution
        else:
            penalty_weight = abs(expected_weight)
            contribution = 1.0 - _clamp(actual)
            denominator += penalty_weight
            numerator += penalty_weight * contribution
    return numerator / denominator if denominator else 0.0


def _compute_cluster_fit(cluster_ranges: dict[str, list[float]], clusters: dict[str, float]) -> float:
    if not cluster_ranges:
        return 0.0
    total = 0.0
    count = 0
    for cluster_name, bounds in cluster_ranges.items():
        count += 1
        min_value, max_value = float(bounds[0]), float(bounds[1])
        value = clusters.get(cluster_name, 0.0)
        if min_value <= value <= max_value:
            total += 1.0
            continue
        distance = min(abs(value - min_value), abs(value - max_value))
        span = max(max_value - min_value, 0.15)
        total += max(0.0, 1.0 - distance / span)
    return total / count if count else 0.0


def _family_signal_bases(signals: dict[str, float]) -> tuple[float, float, float]:
    growth_signal = max(
        0.0,
        signals.get("infancy_signal", 0.0),
        signals.get("gogo_signal", 0.0),
        signals.get("youth_signal", 0.0),
    )
    prime_signal = max(
        0.0,
        signals.get("prime_signal", 0.0),
        signals.get("early_prime_signal", 0.0),
    )
    aging_signal = max(
        0.0,
        signals.get("stability_signal", 0.0),
        signals.get("aristocracy_signal", 0.0),
        signals.get("early_bureaucracy_signal", 0.0),
        signals.get("bureaucracy_signal", 0.0),
    )
    return growth_signal, prime_signal, aging_signal


def _family_consistency_scores(clusters: dict[str, float], signals: dict[str, float]) -> dict[str, float]:
    growth_signal, prime_signal, aging_signal = _family_signal_bases(signals)
    growth = _clamp(
        0.45 * clusters.get("immaturity", 0.0)
        + 0.25 * (1.0 - clusters.get("aging", 0.0))
        + 0.20 * growth_signal
        + 0.10 * (1.0 - clusters.get("administration", 0.0))
    )
    prime = _clamp(
        0.18 * clusters.get("execution", 0.0)
        + 0.18 * clusters.get("administration", 0.0)
        + 0.18 * clusters.get("entrepreneurship", 0.0)
        + 0.18 * clusters.get("integration", 0.0)
        + 0.14 * (1.0 - clusters.get("aging", 0.0))
        + 0.14 * prime_signal
    )
    aging = _clamp(
        0.40 * clusters.get("aging", 0.0)
        + 0.20 * clusters.get("administration", 0.0)
        + 0.20 * (1.0 - clusters.get("entrepreneurship", 0.0))
        + 0.20 * aging_signal
    )
    return {
        "growth_family": growth,
        "prime_family": prime,
        "aging_family": aging,
    }


def _family_gate_passes(
    family_key: str,
    config: dict[str, Any],
    clusters: dict[str, float],
    traits: dict[str, float],
    signals: dict[str, float],
) -> bool:
    rules = (config.get("family_rules") or {}).get(family_key, {})
    gates = rules.get("hard_gates", [])
    return all(_check_gate(gate, clusters, traits, signals) for gate in gates)


def _determine_family(
    config: dict[str, Any],
    clusters: dict[str, float],
    traits: dict[str, float],
    signals: dict[str, float],
) -> dict[str, Any]:
    scores = _family_consistency_scores(clusters, signals)
    candidates: list[dict[str, Any]] = []
    for family_key, score in scores.items():
        candidates.append(
            {
                "family": family_key,
                "score": score,
                "eligible": _family_gate_passes(family_key, config, clusters, traits, signals),
            }
        )
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    eligible = [item for item in ranked if item["eligible"]]
    threshold = float(config.get("family_exact_threshold", 0.58))
    mixed_margin = float(config.get("family_mixed_margin", 0.10))

    if not eligible:
        return {
            "family": "undefined_family",
            "type": "undefined_family",
            "score": 0.0,
            "second_score": 0.0,
            "scores": scores,
            "candidates": ranked,
        }

    best = eligible[0]
    second = eligible[1] if len(eligible) > 1 else None
    if best["score"] < threshold:
        family_type = "mixed_family"
    elif second and abs(best["score"] - second["score"]) < mixed_margin:
        family_type = "mixed_family"
    else:
        family_type = "exact_family"

    return {
        "family": best["family"],
        "type": family_type,
        "score": best["score"],
        "second_score": second["score"] if second else 0.0,
        "scores": scores,
        "candidates": ranked,
    }


def _evaluate_stage(stage_def: dict[str, Any], clusters: dict[str, float], traits: dict[str, float], signals: dict[str, float]) -> dict[str, Any]:
    violated = []
    for gate in stage_def.get("hard_gates", []):
        if not _check_gate(gate, clusters, traits, signals):
            violated.append(gate)

    if violated:
        return {
            "stage": stage_def["label"],
            "family": stage_def["family"],
            "eligible": False,
            "score": 0.0,
            "cluster_fit": 0.0,
            "soft_score": 0.0,
            "anti_score": 0.0,
            "gate_quality": 0.0,
            "violated_gates": violated,
        }

    cluster_fit = _compute_cluster_fit(stage_def.get("cluster_ranges", {}), clusters)
    soft_score = _weighted_match(stage_def.get("soft_signals", {}), traits, signals)
    anti_score = _weighted_match(stage_def.get("anti_signals", {}), traits, signals)
    final_score = max(0.0, 0.45 * cluster_fit + 0.35 * soft_score - 0.20 * anti_score)
    return {
        "stage": stage_def["label"],
        "family": stage_def["family"],
        "eligible": True,
        "score": _clamp(final_score),
        "cluster_fit": cluster_fit,
        "soft_score": soft_score,
        "anti_score": anti_score,
        "gate_quality": 1.0,
        "violated_gates": [],
    }


def _are_adjacent(stage_a: str, stage_b: str, stage_order: dict[str, int]) -> bool:
    return abs(stage_order.get(stage_a, -100) - stage_order.get(stage_b, 100)) == 1


def _classify_stage(
    stage_results: list[dict[str, Any]],
    config: dict[str, Any],
    stage_order: dict[str, int],
    family_result: dict[str, Any],
) -> dict[str, Any]:
    if family_result["type"] == "undefined_family":
        return {
            "classification_type": "undefined",
            "primary_stage": None,
            "secondary_stage": None,
        }

    family_name = family_result["family"].replace("_family", "")
    eligible = [
        item
        for item in stage_results
        if item["eligible"] and item["family"] == family_name
    ]
    if not eligible:
        return {
            "classification_type": "undefined",
            "primary_stage": None,
            "secondary_stage": None,
        }

    ranked = sorted(eligible, key=lambda item: item["score"], reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    min_exact_score = float(config.get("min_exact_score", 0.62))
    transition_margin = float(config.get("transition_margin", 0.08))
    mixed_margin = float(config.get("mixed_margin", 0.12))

    if family_result["type"] != "exact_family" or best["score"] < min_exact_score:
        return {
            "classification_type": "mixed_stage",
            "primary_stage": best["stage"],
            "secondary_stage": second["stage"] if second else None,
        }

    if second and _are_adjacent(best["stage"], second["stage"], stage_order) and abs(best["score"] - second["score"]) < transition_margin:
        return {
            "classification_type": "transitional_state",
            "primary_stage": best["stage"],
            "secondary_stage": second["stage"],
        }

    if second and abs(best["score"] - second["score"]) < mixed_margin:
        return {
            "classification_type": "mixed_stage",
            "primary_stage": best["stage"],
            "secondary_stage": second["stage"],
        }

    return {
        "classification_type": "exact_stage",
        "primary_stage": best["stage"],
        "secondary_stage": second["stage"] if second else None,
    }


def _consistency_score(clusters: dict[str, float], signals: dict[str, float], config: dict[str, Any]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    growth_signal, _, aging_signal = _family_signal_bases(signals)
    contradiction_threshold = float(config.get("contradiction_threshold", 0.58))

    contradiction = 0.0
    if growth_signal > contradiction_threshold and aging_signal > contradiction_threshold:
        contradiction = min(growth_signal, aging_signal)
        warnings.append("signal_contradiction")
        warnings.append("family_contradiction")
    contradiction = max(contradiction, min(clusters.get("immaturity", 0.0), clusters.get("aging", 0.0)))
    return max(0.2, 1.0 - contradiction * 0.7), warnings


def _stage_results_by_name(stage_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["stage"]: item for item in stage_results}


def _compute_confidence(
    validation_result: dict[str, Any],
    stage_results: list[dict[str, Any]],
    classification: dict[str, Any],
    consistency_score: float,
) -> int:
    completeness = float(validation_result["completeness"])
    validity = 1.0 if validation_result["status"] == "ok" else 0.0
    by_name = _stage_results_by_name(stage_results)
    best = by_name.get(classification.get("primary_stage") or "", {})
    second = by_name.get(classification.get("secondary_stage") or "", {})

    best_score = float(best.get("score", 0.0))
    second_score = float(second.get("score", 0.0))
    fit_quality = 0.7 + 0.3 * best_score if best else 0.0
    separation = _clamp(0.8 + 0.5 * max(0.0, best_score - second_score))
    gate_quality = float(best.get("gate_quality", 0.0))
    class_multiplier = {
        "exact_stage": 1.0,
        "transitional_state": 0.82,
        "mixed_stage": 0.55,
        "undefined": 0.0,
    }[classification["classification_type"]]

    confidence = 100 * completeness * validity * fit_quality * separation * consistency_score * gate_quality * class_multiplier
    return round(confidence)


def _enforce_exact_stage_quality(
    classification: dict[str, Any],
    stage_results: list[dict[str, Any]],
    config: dict[str, Any],
    confidence: int,
) -> dict[str, Any]:
    if classification["classification_type"] != "exact_stage":
        return classification
    by_name = _stage_results_by_name(stage_results)
    best = by_name.get(classification.get("primary_stage") or "", {})
    second = by_name.get(classification.get("secondary_stage") or "", {})
    exact_margin = float(config.get("exact_margin", 0.08))
    confidence_min = int(config.get("exact_confidence_min", 60))
    min_exact_score = float(config.get("min_exact_score", 0.60))

    best_score = float(best.get("score", 0.0))
    second_score = float(second.get("score", 0.0))
    gap = best_score - second_score if second else best_score
    if confidence < confidence_min or best_score < min_exact_score or gap < exact_margin:
        return {
            "classification_type": "mixed_stage",
            "primary_stage": classification.get("primary_stage"),
            "secondary_stage": classification.get("secondary_stage"),
        }
    return classification


def _metric_reason(label: str, value: float) -> str:
    pct = round(value * 100)
    return f"{label}: {pct}%."


def _build_explanations(
    assessment: dict[str, Any],
    stage_result: dict[str, Any] | None,
    stage_results: list[dict[str, Any]],
    data: dict[str, Any],
) -> dict[str, list[str]]:
    why_this: list[str] = []
    why_not_prime: list[str] = []

    if stage_result:
        why_this.append(_metric_reason("cluster_fit", stage_result["cluster_fit"]))
        why_this.append(_metric_reason("soft_signals", stage_result["soft_score"]))
        if assessment["classification_type"] != "exact_stage" and assessment.get("secondary_stage"):
            why_this.append(f"Параллельно выражены признаки стадии «{assessment['secondary_stage']}».")

    prime_result = next((item for item in stage_results if item["stage"] == "Расцвет"), None)
    if prime_result:
        if not prime_result["eligible"]:
            why_not_prime.append("Стадия «Расцвет» заблокирована hard-gates.")
        elif prime_result["score"] < float(data["stage_config"].get("min_exact_score", 0.62)):
            why_not_prime.append("Сигналы и кластеры не дают достаточно сильного fit до «Расцвета».")
        if assessment["clusters"]["aging"] >= 0.45:
            why_not_prime.append("Выраженные aging-сигналы снижают вероятность чистого «Расцвета».")
        if assessment["clusters"]["immaturity"] >= 0.45:
            why_not_prime.append("Выраженные immaturity-сигналы указывают на незавершённость системы.")
    return {
        "why_this_stage": why_this[:3],
        "why_not_prime": why_not_prime[:3],
    }


def _select_report_payload(assessment: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    primary_stage = assessment.get("primary_stage")
    secondary_stage = assessment.get("secondary_stage")
    if not primary_stage or primary_stage == "Не определено":
        return {
            "description": data["report_templates_v5"]["classification_descriptions"]["undefined"],
            "normal_problems": [],
            "abnormal_problems": [],
            "what_to_do": [],
            "what_not_to_do": [],
        }

    primary = data["stage_by_name"][primary_stage]
    payload = {
        "description": data["report_templates_v5"]["classification_descriptions"][assessment["classification_type"]],
        "normal_problems": list(primary.get("normal_problems", [])),
        "abnormal_problems": list(primary.get("abnormal_problems", [])),
        "what_to_do": list(primary.get("what_to_do", [])),
        "what_not_to_do": list(primary.get("what_not_to_do", [])),
    }
    if assessment["classification_type"] in {"transitional_state", "mixed_stage"} and secondary_stage and secondary_stage in data["stage_by_name"]:
        secondary = data["stage_by_name"][secondary_stage]
        payload["description"] = (
            f"{data['report_templates_v5']['classification_descriptions'][assessment['classification_type']]} "
            f"Основная траектория ближе к «{primary_stage}», но устойчиво проявляются черты «{secondary_stage}»."
        )
        for key in ("normal_problems", "abnormal_problems", "what_to_do", "what_not_to_do"):
            merged = []
            seen = set()
            for item in list(primary.get(key, [])) + list(secondary.get(key, [])):
                if item in seen:
                    continue
                seen.add(item)
                merged.append(item)
            payload[key] = merged[:5]
    return payload


def _history_direction(history: list[dict[str, Any]], data: dict[str, Any], current_stage: str | None, current_confidence: int) -> tuple[bool, bool]:
    if not current_stage or current_stage == "Не определено":
        return False, False
    window = int(data["stage_config"].get("history_window", 5))
    min_conf = int(data["stage_config"].get("confidence_floor_for_history", 65))
    valid = [
        item for item in history[:window]
        if item.get("stage") in data["stage_by_name"] and int(item.get("confidence", 0) or 0) >= min_conf
    ]
    if len(valid) < 3 or current_confidence < min_conf:
        return False, False

    current_order = data["stage_by_name"].get(current_stage, {}).get("order")
    if current_order is None:
        return False, False
    prev_orders = [data["stage_by_name"][item["stage"]]["order"] for item in valid[:3]]
    prev_median = median(prev_orders)

    if prev_median >= 6 and current_stage == "Расцвет":
        return False, True
    if current_order > prev_median:
        return True, False
    return False, False


def evaluate_assessment_v5(
    answers: dict[str, str],
    data: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    history = history or []
    validation_result = validate_answers(answers, data["questions_by_id"])
    if validation_result["status"] == "invalid":
        warnings = []
        if any(error["type"] == "invalid_answer" for error in validation_result["errors"]):
            warnings.append("invalid_answer")
        if any(error["type"] == "unknown_question" for error in validation_result["errors"]):
            warnings.append("invalid_answer")
        empty_report = {
            "title": "Диагностика содержит ошибки",
            "description": "Исправьте некорректные ответы и запустите расчёт заново.",
            "normal_problems": [],
            "abnormal_problems": [],
            "what_to_do": [],
            "what_not_to_do": [],
        }
        return {
            "status": "invalid",
            "classification_type": "undefined",
            "primary_stage": None,
            "secondary_stage": None,
            "stage": "Не определено",
            "second_best_stage": "",
            "nearest_stage": "",
            "second_stage": "",
            "transition": None,
            "hybrid": False,
            "confidence": 0,
            "regress": False,
            "warnings": warnings,
            "report_text": empty_report["description"],
            "report_json": empty_report,
            "normal_problems": [],
            "abnormal_problems": [],
            "recommendations": [],
            "paei": {"scores": {dim: 0 for dim in DIMENSIONS}, "profile_code": "paei"},
            "indices": {dim: 0 for dim in DIMENSIONS},
            "clusters": {key: 0.0 for key in ("execution", "administration", "entrepreneurship", "integration", "aging", "immaturity")},
            "signals": {},
            "validation": validation_result,
            "stage_results": [],
            "distances": {},
            "candidates": [],
        }

    paei_scores, traits, stage_signals = _score_raw(answers, data["questions_by_id"])
    clusters = _aggregate_clusters(traits, data["traits"])
    profile_code = _profile_code(paei_scores)
    stage_order = {stage["label"]: int(stage["order"]) for stage in data["stages"]}
    stage_results = [_evaluate_stage(stage, clusters, traits, stage_signals) for stage in data["stages"]]
    family_result = _determine_family(data["stage_config"], clusters, traits, stage_signals)
    classification = _classify_stage(stage_results, data["stage_config"], stage_order, family_result)
    consistency_score, consistency_warnings = _consistency_score(clusters, stage_signals, data["stage_config"])
    confidence = _compute_confidence(validation_result, stage_results, classification, consistency_score)
    classification = _enforce_exact_stage_quality(classification, stage_results, data["stage_config"], confidence)
    confidence = _compute_confidence(validation_result, stage_results, classification, consistency_score)

    warnings: list[str] = []
    if validation_result["status"] == "incomplete":
        warnings.append("incomplete")
    warnings.extend(consistency_warnings)
    if classification["classification_type"] == "mixed_stage":
        warnings.append("mixed_stage")
    if classification["classification_type"] == "undefined":
        warnings.append("undefined")
    if family_result["type"] == "mixed_family":
        warnings.append("mixed_stage")
    if family_result["type"] == "undefined_family":
        warnings.append("undefined")
    if confidence < 60:
        warnings.append("low_confidence")

    best_stage_result = next((item for item in stage_results if item["stage"] == classification.get("primary_stage")), None)
    if best_stage_result and best_stage_result["score"] < float(data["stage_config"].get("low_fit_threshold", 0.55)):
        warnings.append("low_fit_quality")
    if any(not item["eligible"] for item in sorted(stage_results, key=lambda row: row["score"], reverse=True)[:2]):
        warnings.append("gate_blocked")

    regress, recovery = _history_direction(history, data, classification.get("primary_stage"), confidence)
    if regress:
        warnings.append("regress_detected")
    if recovery:
        warnings.append("recovery_detected")

    explanations = _build_explanations(
        {
            "classification_type": classification["classification_type"],
            "clusters": clusters,
            "primary_stage": classification.get("primary_stage"),
            "secondary_stage": classification.get("secondary_stage"),
        },
        best_stage_result,
        stage_results,
        data,
    )
    assessment = {
        "status": validation_result["status"],
        "classification_type": classification["classification_type"],
        "primary_stage": classification.get("primary_stage"),
        "secondary_stage": classification.get("secondary_stage"),
        "family": family_result["family"],
        "family_type": family_result["type"],
        "family_score": round(float(family_result.get("score", 0.0)), 3),
        "family_scores": {key: round(value, 3) for key, value in family_result.get("scores", {}).items()},
        "paei": {"scores": paei_scores, "profile_code": profile_code},
        "clusters": {key: round(value, 3) for key, value in clusters.items()},
        "signals": {key: round(value, 3) for key, value in stage_signals.items()},
        "dominant_function": max(DIMENSIONS, key=lambda letter: paei_scores[letter]),
        "deficient_function": min(DIMENSIONS, key=lambda letter: paei_scores[letter]),
        "key_skew": _skew_key(max(DIMENSIONS, key=lambda letter: paei_scores[letter]), min(DIMENSIONS, key=lambda letter: paei_scores[letter])),
        "warnings": list(dict.fromkeys(warnings)),
        "confidence": confidence,
        "validation": validation_result,
        "stage_results": stage_results,
        "explanations": explanations,
    }
    assessment["report_payload"] = _select_report_payload(assessment, data)
    report_text, report_json = build_report_v5(assessment, data)

    ranked_candidates = sorted(stage_results, key=lambda item: item["score"], reverse=True)
    primary_stage = classification.get("primary_stage")
    secondary_stage = classification.get("secondary_stage") or ""
    stage = primary_stage or "Не определено"
    assessment.update(
        {
            "stage": stage,
            "second_best_stage": secondary_stage,
            "nearest_stage": secondary_stage,
            "second_stage": secondary_stage,
            "transition": classification["classification_type"] == "transitional_state",
            "hybrid": classification["classification_type"] == "mixed_stage",
            "regress": regress,
            "recovery": recovery,
            "profile_code": profile_code,
            "indices": paei_scores,
            "distance": round(1.0 - float(best_stage_result["score"]) if best_stage_result else 1.0, 3),
            "distance_gap": round(
                abs(ranked_candidates[0]["score"] - ranked_candidates[1]["score"]),
                3,
            ) if len(ranked_candidates) > 1 else 1.0,
            "admissible_stages": [item["stage"] for item in stage_results if item["eligible"]],
            "candidates": [
                {"stage": item["stage"], "distance": round(1.0 - item["score"], 3), "score": round(item["score"], 3)}
                for item in ranked_candidates[:3]
            ],
            "distances": {item["stage"]: round(1.0 - item["score"], 3) for item in ranked_candidates},
            "report_text": report_text,
            "report_json": report_json,
            "normal_problems": assessment["report_payload"]["normal_problems"],
            "abnormal_problems": assessment["report_payload"]["abnormal_problems"],
            "recommendations": assessment["report_payload"]["what_to_do"],
        }
    )
    return assessment


def use_v5_engine() -> bool:
    return os.getenv("USE_V5_ENGINE", "0").strip().lower() in {"1", "true", "yes", "on"}
