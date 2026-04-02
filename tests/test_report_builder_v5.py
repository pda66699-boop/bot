from __future__ import annotations

import json
import unittest
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
        if result["classification_type"] == "mixed_stage":
            self.assertIn("Смешанный профиль развития", result["report_text"])
        if result["classification_type"] == "undefined":
            self.assertIn("не определена", result["report_text"].lower())
        self.assertEqual(result["report_json"]["normal_problems"], result["normal_problems"])
        self.assertEqual(result["report_json"]["what_to_do"], result["recommendations"])


if __name__ == "__main__":
    unittest.main()
