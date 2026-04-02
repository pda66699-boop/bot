from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from bot.assessment_engine_v5 import evaluate_assessment_v5, load_v5_data


class StageEngineV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_v5_data(Path("data"))
        cls.fixtures_dir = Path("tests/fixtures")

    def _fixture_answers(self, name: str) -> dict[str, str]:
        with (self.fixtures_dir / name).open("r", encoding="utf-8") as file:
            return json.load(file)["answers"]

    def test_prime_fixture(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_prime.json"), self.data, history=[])
        self.assertEqual(result["classification_type"], "exact_stage")
        self.assertEqual(result["stage"], "Расцвет")
        self.assertGreaterEqual(result["confidence"], 70)

    def test_gogo_fixture(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_gogo.json"), self.data, history=[])
        self.assertEqual(result["stage"], "Давай-давай")

    def test_aristocracy_fixture(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_aristocracy.json"), self.data, history=[])
        self.assertEqual(result["stage"], "Аристократизм")

    def test_mixed_no_fit_fixture(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_mixed_no_fit.json"), self.data, history=[])
        self.assertIn(result["classification_type"], {"mixed_stage", "undefined"})
        self.assertNotEqual(result["classification_type"], "exact_stage")

    def test_invalid_answer_does_not_get_bonus(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_invalid_answer.json"), self.data, history=[])
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["confidence"], 0)
        self.assertEqual(result["stage"], "Не определено")

    def test_recovery_case(self) -> None:
        result = evaluate_assessment_v5(
            self._fixture_answers("case_prime.json"),
            self.data,
            history=[
                {"stage": "Стабильность", "confidence": 84},
                {"stage": "Стабильность", "confidence": 82},
                {"stage": "Стабильность", "confidence": 81},
            ],
        )
        self.assertFalse(result["regress"])
        self.assertIn("recovery_detected", result["warnings"])

    def test_stability_not_youth(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_stability.json"), self.data, history=[])
        self.assertEqual(result["family"], "aging_family")
        self.assertEqual(result["stage"], "Стабильность")
        self.assertNotEqual(result["stage"], "Юность")

    def test_early_prime_not_youth(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_early_prime.json"), self.data, history=[])
        self.assertEqual(result["family"], "prime_family")
        self.assertEqual(result["stage"], "Ранний Расцвет")
        self.assertNotEqual(result["stage"], "Юность")

    def test_youth_requires_non_aging_pattern(self) -> None:
        youth_answers = {
            "P1": "C", "P2": "A", "P3": "D", "P4": "C", "P5": "C", "P6": "D",
            "A1": "A", "A2": "D", "A3": "D", "A4": "B", "A5": "B", "A6": "A",
            "E1": "C", "E2": "A", "E3": "B", "E4": "C", "E5": "B", "E6": "C",
            "I1": "B", "I2": "A", "I3": "A", "I4": "D", "I5": "A", "I6": "C",
        }
        baseline = evaluate_assessment_v5(youth_answers, self.data, history=[])
        self.assertEqual(baseline["stage"], "Юность")

        aged = dict(youth_answers)
        aged.update({"P5": "A", "P6": "A", "E1": "D", "E2": "D", "E3": "D", "E4": "D", "E5": "D", "E6": "D"})
        aged_result = evaluate_assessment_v5(aged, self.data, history=[])
        self.assertNotEqual(aged_result["stage"], "Юность")
        self.assertIn(aged_result["family"], {"aging_family", "undefined_family"})

    def test_exact_stage_requires_strong_fit(self) -> None:
        strict_data = deepcopy(self.data)
        strict_data["stage_config"]["exact_confidence_min"] = 90
        result = evaluate_assessment_v5(self._fixture_answers("case_prime.json"), strict_data, history=[])
        self.assertNotEqual(result["classification_type"], "exact_stage")
        self.assertEqual(result["classification_type"], "mixed_stage")

    def test_family_first_classification(self) -> None:
        result = evaluate_assessment_v5(self._fixture_answers("case_early_prime.json"), self.data, history=[])
        self.assertEqual(result["family"], "prime_family")
        self.assertIn(result["stage"], {"Ранний Расцвет", "Расцвет"})
        self.assertNotIn(result["stage"], {"Младенчество", "Давай-давай", "Юность"})

    def test_controversial_index_cases_not_forced(self) -> None:
        case_1 = evaluate_assessment_v5(self._fixture_answers("case_p56_a56_e44_i67.json"), self.data, history=[])
        case_2 = evaluate_assessment_v5(self._fixture_answers("case_p56_a17_e56_i72.json"), self.data, history=[])
        self.assertIn(case_1["classification_type"], {"mixed_stage", "undefined"})
        self.assertIn(case_2["classification_type"], {"mixed_stage", "undefined"})
        self.assertNotEqual(case_1["classification_type"], "exact_stage")
        self.assertNotEqual(case_2["classification_type"], "exact_stage")


if __name__ == "__main__":
    unittest.main()
