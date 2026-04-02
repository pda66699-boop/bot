from __future__ import annotations

import json
import unittest
from pathlib import Path

from bot.assessment_engine_v5 import load_v5_data
from bot.validation_v5 import validate_answers


class ValidationV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_v5_data(Path("data"))
        cls.fixtures_dir = Path("tests/fixtures")

    def _fixture_answers(self, name: str) -> dict[str, str]:
        with (self.fixtures_dir / name).open("r", encoding="utf-8") as file:
            return json.load(file)["answers"]

    def test_incomplete_fixture_returns_incomplete(self) -> None:
        result = validate_answers(self._fixture_answers("case_incomplete.json"), self.data["questions_by_id"])
        self.assertEqual(result["status"], "incomplete")
        self.assertLess(result["completeness"], 1.0)

    def test_invalid_answer_is_validation_error(self) -> None:
        result = validate_answers(self._fixture_answers("case_invalid_answer.json"), self.data["questions_by_id"])
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any(item["type"] == "invalid_answer" for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
