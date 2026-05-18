from __future__ import annotations

import unittest

from braintrust_harbor import ArtifactSpec, SuiteArtifactConfig, normalized_trace_span_records, trace_import_warnings


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
                        "schema_version": "ATIF-v1.4",
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

    def test_tool_observations_are_matched_by_source_call_id(self) -> None:
        records = normalized_trace_span_records(
            {
                "harbor_result": {"status": "done"},
                "trajectory": {
                    "schema_version": "ATIF-v1.4",
                    "steps": [
                        {
                            "source": "agent",
                            "message": "I will call two tools",
                            "tool_calls": [
                                {"tool_call_id": "call_1", "function_name": "first", "arguments": {}},
                                {"tool_call_id": "call_2", "function_name": "second", "arguments": {}},
                            ],
                            "observation": {
                                "results": [
                                    {"source_call_id": "call_2", "content": "second result"},
                                    {"source_call_id": "call_1", "content": "first result"},
                                ]
                            },
                        }
                    ],
                },
            }
        )

        first = next(record for record in records if record["name"] == "agent.tool.first")
        second = next(record for record in records if record["name"] == "agent.tool.second")
        self.assertEqual(first["output"], "first result")
        self.assertEqual(second["output"], "second result")

    def test_trace_import_warnings_flag_nonstandard_trajectory_shapes(self) -> None:
        output = {
            "harbor_result": {"status": "done"},
            "trajectory": {
                "schema_version": "custom-v0",
                "steps": [
                    {"source": "agent", "tool_calls": {"not": "a list"}},
                    {"source": "surprise"},
                ],
            },
        }

        warnings = trace_import_warnings(output)
        self.assertIn("trial: unsupported ATIF schema_version 'custom-v0'", warnings)
        self.assertIn("trial: step 1 tool_calls is not a list", warnings)
        self.assertIn("trial: step 2 has unsupported source 'surprise'", warnings)

        harbor_record = normalized_trace_span_records(output)[0]
        self.assertEqual(harbor_record["metadata"]["trace_import_warnings"], warnings)


if __name__ == "__main__":
    unittest.main()
