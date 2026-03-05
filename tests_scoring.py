from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot.flows import _build_admin_summary_text
from bot.scoring import (
    build_profile_code,
    calculate_indices,
    determine_stage,
    evaluate_assessment,
    load_data,
)
from bot.sheets import GoogleSheetsLogger
from bot.storage import SQLiteStore


class ScoringV41Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_data(Path("data"))
        cls.questions = cls.data["questions"]
        cls.questions_by_id = cls.data["questions_by_id"]

    def test_stage_list_has_early_prime(self) -> None:
        names = [s["name"] for s in self.data["stages"]]
        self.assertEqual(
            names,
            [
                "Младенчество",
                "Давай-давай",
                "Юность",
                "Ранний Расцвет",
                "Расцвет",
                "Стабильность",
                "Аристократизм",
                "Ранний бюрократизм",
                "Бюрократия",
            ],
        )

    def test_fixture_denzel_should_be_prime(self) -> None:
        indices = {"P": 72, "A": 61, "E": 67, "I": 83}
        stage_result = determine_stage(indices, self.data["stages"], self.data.get("scoring_config", {}), history=[])
        self.assertEqual(stage_result["stage"], "Расцвет")
        self.assertFalse(stage_result["regress"])
        self.assertEqual(stage_result["confidence"], 100)

    def test_early_prime_gate(self) -> None:
        result = determine_stage(
            {"P": 75, "A": 70, "E": 70, "I": 60},
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertEqual(result["stage"], "Ранний Расцвет")

    def test_stability_requires_low_e(self) -> None:
        ok = determine_stage(
            {"P": 70, "A": 70, "E": 59, "I": 70},
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertEqual(ok["stage"], "Стабильность")

        blocked = determine_stage(
            {"P": 70, "A": 70, "E": 61, "I": 70},
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertNotEqual(blocked["stage"], "Стабильность")

    def test_gogo_requires_low_i(self) -> None:
        ok = determine_stage(
            {"P": 80, "A": 50, "E": 80, "I": 50},
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertEqual(ok["stage"], "Давай-давай")

        blocked = determine_stage(
            {"P": 80, "A": 50, "E": 80, "I": 65},
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertNotEqual(blocked["stage"], "Давай-давай")

    def test_recovery_not_regress(self) -> None:
        indices = {"P": 72, "A": 61, "E": 67, "I": 83}
        history = [
            {"run_id": "r1", "stage": "Стабильность", "confidence": 95},
            {"run_id": "r2", "stage": "Стабильность", "confidence": 94},
            {"run_id": "r3", "stage": "Стабильность", "confidence": 93},
        ]
        result = determine_stage(indices, self.data["stages"], self.data.get("scoring_config", {}), history=history)
        self.assertEqual(result["stage"], "Расцвет")
        self.assertFalse(result["regress"])

    def test_regress_history_confidence(self) -> None:
        indices = {"P": 80, "A": 50, "E": 80, "I": 50}

        low_conf = determine_stage(
            indices,
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[
                {"run_id": "r1", "stage": "Расцвет", "confidence": 60},
                {"run_id": "r2", "stage": "Расцвет", "confidence": 90},
                {"run_id": "r3", "stage": "Расцвет", "confidence": 88},
            ],
        )
        self.assertFalse(low_conf["regress"])

        high_conf = determine_stage(
            indices,
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[
                {"run_id": "r1", "stage": "Расцвет", "confidence": 90},
                {"run_id": "r2", "stage": "Расцвет", "confidence": 89},
                {"run_id": "r3", "stage": "Расцвет", "confidence": 88},
            ],
        )
        self.assertTrue(high_conf["regress"])

    def test_report_order_and_warnings(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        history = [
            {"run_id": "", "stage": "Стабильность", "confidence": 95},
            {"run_id": "r2", "stage": "Стабильность", "confidence": 94},
            {"run_id": "r3", "stage": "Стабильность", "confidence": 93},
        ]
        assessment = evaluate_assessment(answers, self.data, history=history)

        self.assertIn("warnings", assessment)
        self.assertIn("history_migrated_or_inconsistent", assessment["warnings"])
        report = assessment["report_text"]
        self.assertLess(report.find("📈 Индексы"), report.find("🧭 Описание"))

    def test_register_rule_consistent(self) -> None:
        profile = build_profile_code({"P": 72, "A": 61, "E": 67, "I": 83})
        self.assertEqual(profile, "PaeI")

    def test_answers_processing_consistency_and_inversions(self) -> None:
        for qid in ("P5", "P6", "I6"):
            question = self.questions_by_id[qid]
            a_points = calculate_indices({qid: "A"}, {qid: question})[question["dim"]]
            d_points = calculate_indices({qid: "D"}, {qid: question})[question["dim"]]
            self.assertEqual(a_points, 0)
            self.assertEqual(d_points, 17)

    def test_append_only_runs_storage(self) -> None:
        with TemporaryDirectory() as td:
            store = SQLiteStore(Path(td) / "test.db")
            store.save_result(101, "Расцвет", "run-1", 91, False)
            store.save_result(101, "Стабильность", "run-2", 84, True)
            history = store.get_recent_results(101, limit=10)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["run_id"], "run-2")
            self.assertEqual(history[1]["run_id"], "run-1")

    def test_append_only_sheets_mock(self) -> None:
        logger = GoogleSheetsLogger.__new__(GoogleSheetsLogger)
        logger.ws = SimpleNamespace(append_row=Mock())
        logger.logger = SimpleNamespace(warning=Mock(), exception=Mock())

        logger.append_run_row({"run_id": "r1", "telegram_id": 1, "stage": "Расцвет"})
        logger.append_run_row({"run_id": "r2", "telegram_id": 1, "stage": "Расцвет"})

        self.assertEqual(logger.ws.append_row.call_count, 2)

    def test_no_admissible_stage_fallback(self) -> None:
        indices = {"P": 56, "A": 17, "E": 56, "I": 72}
        stage_result = determine_stage(
            indices,
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        self.assertEqual(stage_result["admissible_stages"], [])
        self.assertTrue(stage_result["no_admissible_stage"])
        self.assertTrue(stage_result["hybrid"])
        self.assertLessEqual(stage_result["confidence"], 55)

        by_distance = sorted(stage_result["distances"].items(), key=lambda x: x[1])
        self.assertEqual(stage_result["stage"], by_distance[0][0])
        self.assertEqual(stage_result["second_best_stage"], by_distance[1][0])
        self.assertEqual(stage_result["nearest_stage"], by_distance[1][0])

    def test_no_admissible_stage_warnings_in_assessment(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 56, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        self.assertIn("no_admissible_stage", assessment["warnings"])
        self.assertIn("low_confidence", assessment["warnings"])
        self.assertTrue(assessment["hybrid"])
        self.assertLessEqual(assessment["confidence"], 55)
        self.assertIn("🏁 Текущая модель развития: ближе всего к стадии «", assessment["report_text"])
        self.assertIn("Также компания показывает признаки стадии:", assessment["report_text"])
        self.assertNotIn("Переход:", assessment["report_text"])
        self.assertNotIn("Гибрид:", assessment["report_text"])
        header = assessment["report_text"].splitlines()[0]
        self.assertIn("ближе всего", header)

    def test_fallback_warning_and_deficit_priority(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 56, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        report = assessment["report_text"]
        self.assertIn("показывает смешанные признаки разных стадий развития", report)
        do_part = report.split("✅ Что делать\n", 1)[1]
        first_do = do_part.splitlines()[0]
        self.assertIn("Усилить A", first_do)

    def test_hybrid_flag_is_consistent_in_report_and_sheet_row(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 56, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        self.assertIn("Текущая модель развития", assessment["report_text"])
        self.assertTrue(assessment["hybrid"])

        logger = GoogleSheetsLogger.__new__(GoogleSheetsLogger)
        row = logger._build_row(  # pylint: disable=protected-access
            {
                "run_id": "run-hybrid",
                "stage": assessment["stage"],
                "nearest_stage": assessment["second_best_stage"],
                "hybrid": assessment["hybrid"],
                "transition": assessment["transition"] or "",
                "regress": assessment["regress"],
                "warnings": ", ".join(assessment["warnings"]),
            }
        )
        hybrid_idx = GoogleSheetsLogger.COLUMN_ORDER.index("hybrid")
        self.assertTrue(row[hybrid_idx])

        admin_text = _build_admin_summary_text(
            assessment=assessment,
            run_id="run-hybrid",
            respondent_name="User",
            respondent_revenue="1-5",
            shared_tg=True,
            telegram_link="tg://user?id=1",
        )
        self.assertIn("Гибрид: да", admin_text)
        self.assertIn("Переход: нет", admin_text)
        self.assertNotIn("Переход/гибрид", admin_text)

    def test_user_report_has_no_internal_terms(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 56, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        report_lower = assessment["report_text"].lower()
        for term in ("distance", "admissibility", "fallback", "admissible", "classification"):
            self.assertNotIn(term, report_lower)

    def test_index_interpretation_levels(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 39, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        report = assessment["report_text"]
        self.assertIn("P — результат и клиент: 56 (средний уровень)", report)
        self.assertIn("A — система и порядок: 17 (критически слабая функция)", report)
        self.assertIn("E — развитие и возможности: 39 (слабая функция)", report)
        self.assertIn("I — команда и согласованность: 72 (сильная функция)", report)

    def test_prime_has_no_weak_functions(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 89, "A": 100, "E": 100, "I": 83}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        report = assessment["report_text"]
        self.assertIn("Все управленческие функции развиты на высоком уровне.", report)
        self.assertIn("Явных слабых функций не выявлено.", report)
        self.assertIn("Самая слабая функция: не выявлена", report)

    def test_management_skew(self) -> None:
        answers = {q["id"]: "B" for q in self.questions}
        with patch("bot.scoring.calculate_indices", return_value={"P": 56, "A": 17, "E": 56, "I": 72}):
            assessment = evaluate_assessment(answers, self.data, history=[])

        report = assessment["report_text"]
        self.assertIn("Сильная функция: I", report)
        self.assertIn("Слабая функция: A", report)
        self.assertIn("сильная I при слабой A", report)

    def test_fallback_candidates_top3_for_test1(self) -> None:
        indices = {"P": 56, "A": 17, "E": 56, "I": 72}
        stage_result = determine_stage(
            indices,
            self.data["stages"],
            self.data.get("scoring_config", {}),
            history=[],
        )
        top3 = stage_result["candidates"][:3]
        expected = [
            ("Младенчество", 42.72),
            ("Расцвет", 49.143),
            ("Давай-давай", 52.202),
        ]
        self.assertEqual([item["stage"] for item in top3], [x[0] for x in expected])
        for item, (_, exp_distance) in zip(top3, expected):
            self.assertAlmostEqual(float(item["distance"]), exp_distance, places=3)


if __name__ == "__main__":
    unittest.main()
