from __future__ import annotations

import unittest

from braintrust_harbor import ArtifactSpec, SuiteArtifactConfig, normalized_trace_span_records


class TraceNormalizationTests(unittest.TestCase):
    def test_command_spans_are_suite_configured(self) -> None:
        output = {
            "harbor_result": {"status": "done"},
            "commands": [{"command_class": "inspect", "argv": ["tool", "inspect"], "stdout": "ok"}],
        }

        default_records = normalized_trace_span_records(output)
        self.assertEqual([record["name"] for record in default_records], ["harbor.trial"])

        suite_artifacts = SuiteArtifactConfig(
            artifacts=(ArtifactSpec(key="commands", paths=("commands.jsonl",), kind="jsonl"),),
            command_log_key="commands",
            command_span_prefix="tool",
            command_tool_name="example-tool",
        )
        records = normalized_trace_span_records(output, suite_artifacts=suite_artifacts)

        self.assertEqual([record["name"] for record in records], ["harbor.trial", "tool.inspect"])
        self.assertEqual(records[1]["metadata"]["tool_name"], "example-tool")

    def test_step_trajectories_are_included_in_normalized_trace(self) -> None:
        output = {
            "agent": "codex",
            "model": "openai/gpt-test",
            "harbor_result": {"status": "done"},
            "steps": {
                "run": {
                    "runtime_dir": "/tmp/job/trial/steps/run",
                    "trajectory": {
                        "steps": [
                            {
                                "source": "agent",
                                "message": "I will inspect the repo",
                                "model_name": "gpt-test",
                                "metrics": {"prompt_tokens": 4, "completion_tokens": 6},
                                "tool_calls": [{"function_name": "shell", "arguments": {"cmd": "ls"}}],
                            }
                        ]
                    },
                }
            },
        }

        records = normalized_trace_span_records(output)
        names = [record["name"] for record in records]

        self.assertIn("harbor.step.run", names)
        self.assertIn("agent.message", names)
        self.assertIn("agent.tool.shell", names)
        step_record = next(record for record in records if record["name"] == "harbor.step.run")
        self.assertEqual(step_record["metadata"]["normalized_kind"], "harness_step")
        self.assertEqual(step_record["metadata"]["step_name"], "run")


if __name__ == "__main__":
    unittest.main()
