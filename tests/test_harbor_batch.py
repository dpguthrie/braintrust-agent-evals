from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from braintrust_harbor import HarborBatchConfig, run_harbor_batch


class HarborBatchTests(unittest.TestCase):
    def test_missing_harbor_binary_returns_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_harbor_batch(
                HarborBatchConfig(
                    job_name="missing-harbor",
                    config_path=str(Path(tmp) / "config.json"),
                    jobs_dir=tmp,
                    harbor_bin="definitely-not-a-real-harbor-binary",
                    timeout_sec=1,
                )
            )

            self.assertEqual(result.returncode, 127)
            self.assertIsNone(result.job_dir)
            self.assertIn("Harbor binary not found", result.error or "")
            self.assertEqual(result.command[:3], ["definitely-not-a-real-harbor-binary", "run", "--config"])


if __name__ == "__main__":
    unittest.main()
