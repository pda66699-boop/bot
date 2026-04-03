from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from bot.assessment_engine_v5 import evaluate_assessment_v5, load_v5_data


class ReportBuilderV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_v5_data(Path("data"))
        with Path("tests/fixtures/case_mixed_no_fit.json").open("r", encoding="utf-8") as file:
            cls.mixed_answers = json.load(file)["answers"]

    def test_report_is_consistent_with_classification(self) -> None:
        result = evaluate_assessment_v5(self.mixed_answers, self.data, history=[])
        self.assertIn("Краткий вывод", result["report_text"])
        self.assertIn("Как это выглядит у тебя в бизнесе", result["report_text"])
        self.assertIn("📊 Профиль управления", result["report_text"])
        self.assertEqual(result["report_json"]["normal_problems"], result["normal_problems"])
        self.assertEqual(result["report_json"]["what_to_do"], result["recommendations"])

    def test_undefined_interpretation_has_business_language_structure(self) -> None:
        strict_data = deepcopy(self.data)
        strict_data["stage_config"]["low_fit_threshold"] = 0.99
        result = evaluate_assessment_v5(self.mixed_answers, strict_data, history=[])

        self.assertEqual(result["classification_type"], "undefined")
        self.assertEqual(result.get("interpretation_mode"), "business_language_adapted")
        self.assertTrue(result["report_json"]["description"])
        self.assertGreaterEqual(len(result["normal_problems"]), 3)
        self.assertGreaterEqual(len(result["abnormal_problems"]), 3)
        self.assertGreaterEqual(len(result["recommendations"]), 3)

        text = result["report_text"]
        self.assertIn("Стадия не определена осознанно", text)
        self.assertIn("Что делать сейчас", text)
        self.assertIn("Ввести", text)
        self.assertNotIn("Недостаточно данных для содержательной рекомендации", text)
        self.assertNotIn("result_without_system", text)

    def test_report_has_compact_paei_after_main_interpretation(self) -> None:
        result = evaluate_assessment_v5(self.mixed_answers, self.data, history=[])
        text = result["report_text"]

        idx_summary = text.find("Краткий вывод")
        idx_actions = text.find("Что делать сейчас")
        idx_paei = text.find("📊 Профиль управления")

        self.assertGreaterEqual(idx_summary, 0)
        self.assertGreaterEqual(idx_actions, 0)
        self.assertGreaterEqual(idx_paei, 0)
        self.assertLess(idx_summary, idx_paei)
        self.assertLess(idx_actions, idx_paei)

        for line in (
            "P:",
            "A:",
            "E:",
            "I:",
            "— производство результата",
            "— порядок, эффективность",
            "— развитие, новые продукты",
            "— команда, коммуникации",
        ):
            self.assertIn(line, text)

    def test_report_has_no_internal_labels(self) -> None:
        result = evaluate_assessment_v5(self.mixed_answers, self.data, history=[])
        text = result["report_text"]

        for token in (
            "classification_type",
            "result_without_system",
            "growth_unstructured",
            "aging_bureaucratic",
            "decision_factors",
            "clusters",
            "signals",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
