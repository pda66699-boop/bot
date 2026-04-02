from __future__ import annotations

import os
import unittest
from pathlib import Path

from bot.assessment import load_runtime_data


class ParityV5Tests(unittest.TestCase):
    def test_runtime_loader_uses_v5_flag(self) -> None:
        previous = os.environ.get("USE_V5_ENGINE")
        os.environ["USE_V5_ENGINE"] = "1"
        try:
            data = load_runtime_data(Path("data"))
            self.assertEqual(data.get("version"), "v5")
        finally:
            if previous is None:
                os.environ.pop("USE_V5_ENGINE", None)
            else:
                os.environ["USE_V5_ENGINE"] = previous


if __name__ == "__main__":
    unittest.main()
