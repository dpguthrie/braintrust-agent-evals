from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from braintrust_harbor import (
    ArtifactSpec,
    SuiteArtifactConfig,
    load_harbor_job_outputs,
    load_harbor_trial_output,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class ArtifactLoadingTests(unittest.TestCase):
    def test_loads_harbor_trial_with_suite_artifacts_and_neutral_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "tasks" / "sample"
            task.mkdir(parents=True)
            _write_json(
                task / ".agent-tooling-eval.json",
                {
                    "input": {"prompt": "debug this tool"},
                    "expected": {"route": "fix_tooling"},
                    "metadata": {"tool_version": "1.2.3"},
                },
            )

            job = root / "jobs" / "job-1"
            trial = job / "trial-1"
            _write_json(job / "config.json", {"job": "config"})
            _write_json(job / "result.json", {"job": "result"})
            _write_json(trial / "config.json", {"task": {"path": str(task)}, "agent": {"name": "codex", "model_name": "openai/gpt-test"}})
            _write_json(trial / "result.json", {"started_at": "2026-05-17T00:00:00Z", "finished_at": "2026-05-17T00:00:02Z"})
            _write_json(trial / "verifier" / "reward.json", {"score": 1})
            _write_json(trial / "verifier" / "reward-details.json", {"ok": True})
            _write_json(trial / "artifacts" / "summary.json", {"status": "done"})
            (trial / "artifacts" / "commands.jsonl").write_text('{"command_class":"inspect","argv":["tool","inspect"]}\n', encoding="utf-8")
            _write_json(
                trial / "agent" / "trajectory.json",
                {"steps": [{"source": "agent", "message": "done", "metrics": {"prompt_tokens": 10, "completion_tokens": 5}}]},
            )

            suite_artifacts = SuiteArtifactConfig(
                artifacts=(
                    ArtifactSpec(key="summary", paths=("summary.json",), kind="json"),
                    ArtifactSpec(key="commands", paths=("commands.jsonl",), kind="jsonl"),
                ),
                command_log_key="commands",
            )

            outputs = load_harbor_job_outputs(job, suite_artifacts=suite_artifacts)

            self.assertEqual(len(outputs), 1)
            output = outputs[0]
            self.assertEqual(output["summary"], {"status": "done"})
            self.assertEqual(output["commands"][0]["command_class"], "inspect")
            self.assertEqual(output["reward"], {"score": 1.0})
            self.assertEqual(output["task_metadata"]["metadata"]["tool_version"], "1.2.3")
            self.assertEqual(output["eval_input"], {"prompt": "debug this tool"})
            self.assertEqual(output["expected"], {"route": "fix_tooling"})
            self.assertEqual(output["agent"], "codex")
            self.assertEqual(output["model"], "openai/gpt-test")
            self.assertEqual(output["usage_metrics"]["total_tokens"], 15)

    def test_loads_step_runtime_dirs_and_aggregates_usage_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "jobs" / "job-1"
            trial = job / "trial-1"
            step = trial / "steps" / "verify"
            _write_json(trial / "config.json", {"agent": {"name": "claude-code", "model_name": "anthropic/test"}})
            _write_json(trial / "result.json", {"status": "done"})
            _write_json(step / "verifier" / "reward.json", 0.5)
            _write_json(step / "artifacts" / "commands.jsonl", {"command_class": "check", "argv": ["check"]})
            _write_json(
                step / "agent" / "trajectory.json",
                {
                    "steps": [
                        {"source": "agent", "message": "thinking", "metrics": {"input_tokens": 7, "output_tokens": 3}},
                        {"source": "environment", "message": "ok"},
                    ]
                },
            )

            suite_artifacts = SuiteArtifactConfig(
                artifacts=(ArtifactSpec(key="commands", paths=("commands.jsonl",), kind="jsonl"),),
                command_log_key="commands",
            )

            output = load_harbor_trial_output(job_dir=job, trial_dir=trial, suite_artifacts=suite_artifacts)

            self.assertIn("verify", output["steps"])
            self.assertEqual(output["steps"]["verify"]["reward"], {"reward": 0.5})
            self.assertEqual(output["steps"]["verify"]["commands"][0]["command_class"], "check")
            self.assertEqual(output["usage_metrics"]["input_tokens"], 7)
            self.assertEqual(output["usage_metrics"]["output_tokens"], 3)
            self.assertEqual(output["usage_metrics"]["total_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
