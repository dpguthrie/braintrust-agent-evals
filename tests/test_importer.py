from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from braintrust_harbor import (
    ArtifactSpec,
    ImportedTrace,
    SuiteArtifactConfig,
    TraceLike,
    import_harbor_job_to_braintrust,
)
from braintrust_harbor.braintrust_importer import ScorerArgs, score_trial


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class FakeBraintrustSpan:
    def __init__(
        self,
        *,
        name: str | None = None,
        span_attributes: dict[str, Any] | None = None,
        **event: Any,
    ) -> None:
        self.name = name
        self.span_attributes = span_attributes or {}
        self.event = event
        self.logs: list[dict[str, Any]] = []
        self.children: list[FakeBraintrustSpan] = []
        self.ended = False
        self.end_time: float | None = None

    def start_span(
        self,
        name: str | None = None,
        type: str | None = None,
        span_attributes: dict[str, Any] | None = None,
        **event: Any,
    ) -> "FakeBraintrustSpan":
        attributes = dict(span_attributes or {})
        if type is not None:
            attributes.setdefault("type", type)
        child = FakeBraintrustSpan(name=name, span_attributes=attributes, **event)
        self.children.append(child)
        return child

    def log(self, **event: Any) -> None:
        self.logs.append(event)
        self.event.update({key: value for key, value in event.items() if value is not None})

    def end(self, end_time: float | None = None) -> None:
        self.ended = True
        self.end_time = end_time

    def close(self) -> None:
        self.end()


class FakeBraintrustExperiment:
    id = "fake-experiment-id"

    def __init__(self) -> None:
        self.spans: list[FakeBraintrustSpan] = []

    def start_span(self, **event: Any) -> FakeBraintrustSpan:
        span = FakeBraintrustSpan(**event)
        self.spans.append(span)
        return span

    def summarize(self) -> dict[str, Any]:
        return {"span_count": len(self.spans)}


class FakeOnlineTrace:
    def __init__(self, spans: list[Any]) -> None:
        self._spans = spans

    def get_configuration(self) -> dict[str, str]:
        return {
            "object_type": "experiment",
            "object_id": "experiment-id",
            "root_span_id": "root-span-id",
        }

    async def get_spans(self, span_type: list[str] | None = None) -> list[Any]:
        if not span_type:
            return list(self._spans)
        allowed = set(span_type)
        return [
            span
            for span in self._spans
            if (span.span_attributes or {}).get("type") in allowed
        ]

    async def get_thread(self, _options: Any = None) -> list[Any]:
        return []


class BraintrustImporterTests(unittest.TestCase):
    def test_score_trial_supports_async_scorers_inside_existing_event_loop(self) -> None:
        async def async_scorer(scorer_args: ScorerArgs) -> dict[str, object]:
            await asyncio.sleep(0)
            spans = await scorer_args.trace.get_spans(["function"]) if scorer_args.trace else []
            self.assertEqual(scorer_args.input, {"prompt": "run"})
            self.assertEqual(scorer_args.expected, {"ok": True})
            self.assertEqual(scorer_args.metadata, {"variant": "docs"})
            self.assertEqual([span.name for span in spans], ["harbor.trial"])
            return {"name": "Async Quality", "score": 0.75, "metadata": {"reason": "ok"}}

        async def run_inside_loop() -> tuple[dict[str, float], dict[str, object]]:
            return score_trial(
                {"harbor_result": {"status": "done"}},
                input={"prompt": "run"},
                expected={"ok": True},
                metadata={"variant": "docs"},
                scorers=(async_scorer,),
            )

        scores, details = asyncio.run(run_inside_loop())

        self.assertEqual(scores, {"Async Quality": 0.75})
        self.assertEqual(details["scorers"][0]["scores"][0]["metadata"], {"reason": "ok"})

    def test_score_trial_passes_braintrust_style_keyword_arguments(self) -> None:
        def keyword_scorer(input: object, output: object, expected: object = None, metadata: object = None, trace: object = None) -> list[dict[str, object]]:
            self.assertEqual(input, {"prompt": "run"})
            self.assertEqual(output["summary"], {"ok": True})
            self.assertEqual(expected, {"ok": True})
            self.assertEqual(metadata, {"variant": "docs"})
            self.assertIsNotNone(trace)
            return [
                {"name": "Input wired", "score": 1},
                {"name": "Output wired", "score": 1},
            ]

        scores, _details = score_trial(
            {"summary": {"ok": True}, "harbor_result": {"status": "done"}},
            input={"prompt": "run"},
            expected={"ok": True},
            metadata={"variant": "docs"},
            scorers=(keyword_scorer,),
        )

        self.assertEqual(scores, {"Input wired": 1.0, "Output wired": 1.0})

    def test_trace_level_scorer_runs_against_offline_and_online_trace_like(self) -> None:
        async def tool_trace_scorer(
            input: object = None,
            output: object = None,
            expected: object = None,
            metadata: object = None,
            trace: TraceLike | None = None,
        ) -> dict[str, object]:
            self.assertIsNotNone(trace)
            spans = await trace.get_spans(["tool"]) if trace is not None else []
            command_classes = [
                (getattr(span, "metadata", None) or {}).get("command_class")
                for span in spans
            ]
            return {
                "name": "Tool trace present",
                "score": 1.0 if "inspect" in command_classes else 0.0,
                "metadata": {"command_classes": command_classes},
            }

        output = {
            "harbor_result": {"status": "done"},
            "commands": [{"command_class": "inspect", "argv": ["tool", "inspect"], "stdout": "ok"}],
        }
        suite_artifacts = SuiteArtifactConfig(
            artifacts=(ArtifactSpec(key="commands", paths=("commands.jsonl",), kind="jsonl"),),
            command_log_key="commands",
            command_span_prefix="tool",
        )
        offline_scores, _offline_details = score_trial(
            output,
            scorers=(tool_trace_scorer,),
            suite_artifacts=suite_artifacts,
        )

        online_trace = FakeOnlineTrace(
            [
                SimpleNamespace(
                    span_attributes={"type": "tool"},
                    metadata={"command_class": "inspect"},
                )
            ]
        )
        online_result = asyncio.run(tool_trace_scorer(trace=online_trace))

        self.assertEqual(offline_scores, {"Tool trace present": 1.0})
        self.assertEqual(online_result["score"], 1.0)
        self.assertIsInstance(ImportedTrace([], job_dir="job", trial_dir="trial"), dict)

    def test_score_trial_preserves_skipped_scores_and_scorer_errors(self) -> None:
        def skipped(**_kwargs: object) -> None:
            return None

        def broken(**_kwargs: object) -> dict[str, object]:
            raise RuntimeError("scorer exploded")

        scores, details = score_trial(
            {"harbor_result": {"status": "done"}},
            scorers=(skipped, broken),
        )

        self.assertEqual(scores, {"skipped": None})
        self.assertIn("broken", details["errors"])

    def test_import_preview_writes_one_row_per_harbor_trial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "tasks" / "sample"
            task.mkdir(parents=True)
            _write_json(task / ".agent-tooling-eval.json", {"input": {"prompt": "run"}, "expected": {"ok": True}, "metadata": {"variant": "docs"}})

            job = root / "jobs" / "job-1"
            trial = job / "trial-1"
            _write_json(job / "config.json", {})
            _write_json(job / "result.json", {})
            _write_json(trial / "config.json", {"task": {"path": str(task)}, "agent": {"name": "codex", "model_name": "openai/test"}})
            _write_json(trial / "result.json", {"status": "done"})
            _write_json(trial / "verifier" / "reward.json", {"score": 1})
            _write_json(trial / "artifacts" / "summary.json", {"ok": True})

            def scorer(**_kwargs: object) -> dict[str, object]:
                return {"name": "Contract", "score": 1}

            suite_artifacts = SuiteArtifactConfig(
                artifacts=(ArtifactSpec(key="summary", paths=("summary.json",), kind="json"),),
            )
            preview = root / "preview.json"
            result = import_harbor_job_to_braintrust(
                job_dir=str(job),
                project="Example",
                experiment_name="harbor-job",
                scorers=(scorer,),
                upload=False,
                preview_path=str(preview),
                suite_artifacts=suite_artifacts,
            )

            self.assertEqual(result.row_count, 1)
            payload = json.loads(preview.read_text(encoding="utf-8"))
            row = payload["rows"][0]
            self.assertEqual(row["input"], {"prompt": "run"})
            self.assertEqual(row["expected"], {"ok": True})
            self.assertEqual(row["output"]["summary"], {"ok": True})
            self.assertEqual(row["scores"], {"Contract": 1.0})
            self.assertEqual(row["metadata"]["variant"], "docs")

    def test_upload_logs_eval_task_harbor_agent_and_scorer_spans(self) -> None:
        try:
            import braintrust
        except ImportError:
            self.skipTest("braintrust package is not installed")

        original_init = braintrust.init
        fake_experiment = FakeBraintrustExperiment()

        def fake_init(**_kwargs: object) -> FakeBraintrustExperiment:
            return fake_experiment

        braintrust.init = fake_init
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                task = root / "tasks" / "sample"
                task.mkdir(parents=True)
                _write_json(
                    task / ".agent-tooling-eval.json",
                    {"input": {"prompt": "run"}, "expected": {"ok": True}, "metadata": {"variant": "docs"}},
                )

                job = root / "jobs" / "job-1"
                trial = job / "trial-1"
                _write_json(job / "config.json", {})
                _write_json(job / "result.json", {})
                _write_json(
                    trial / "config.json",
                    {"task": {"path": str(task)}, "agent": {"name": "codex", "model_name": "openai/test"}},
                )
                _write_json(
                    trial / "result.json",
                    {
                        "status": "done",
                        "started_at": "2026-01-01T00:00:00Z",
                        "finished_at": "2026-01-01T00:00:10Z",
                        "agent_execution": {
                            "started_at": "2026-01-01T00:00:01Z",
                            "finished_at": "2026-01-01T00:00:09Z",
                        },
                    },
                )
                _write_json(trial / "verifier" / "reward.json", {"score": 1})
                (trial / "artifacts" / "commands.jsonl").parent.mkdir(parents=True, exist_ok=True)
                (trial / "artifacts" / "commands.jsonl").write_text(
                    '{"command_class":"inspect","argv":["tool","inspect"],"stdout":"ok"}\n',
                    encoding="utf-8",
                )
                _write_json(
                    trial / "agent" / "trajectory.json",
                    {
                        "steps": [
                            {
                                "timestamp": "2026-01-01T00:00:02Z",
                                "source": "agent",
                                "message": "I inspected the tool",
                                "metrics": {"prompt_tokens": 3, "completion_tokens": 4},
                                "tool_calls": [{"function_name": "shell", "arguments": {"cmd": "tool inspect"}}],
                                "observation": {"results": [{"content": "ok"}]},
                            },
                            {
                                "timestamp": "2026-01-01T00:00:05Z",
                                "source": "user",
                                "message": "observation",
                            }
                        ]
                    },
                )

                def contract_score(**_kwargs: object) -> dict[str, object]:
                    return {"name": "Contract", "score": 1, "metadata": {"reason": "ok"}}

                suite_artifacts = SuiteArtifactConfig(
                    artifacts=(ArtifactSpec(key="commands", paths=("commands.jsonl",), kind="jsonl"),),
                    command_log_key="commands",
                    command_span_prefix="tool",
                )

                result = import_harbor_job_to_braintrust(
                    job_dir=str(job),
                    project="Example",
                    experiment_name="harbor-job",
                    scorers=(contract_score,),
                    upload=True,
                    suite_artifacts=suite_artifacts,
                )
        finally:
            braintrust.init = original_init

        self.assertEqual(result.experiment_id, "fake-experiment-id")
        self.assertEqual(len(fake_experiment.spans), 1)
        eval_span = fake_experiment.spans[0]
        self.assertEqual(eval_span.name, "eval")
        self.assertEqual(eval_span.span_attributes, {"type": "eval"})
        self.assertEqual(eval_span.event["start_time"], 1767225600.0)
        self.assertEqual(eval_span.end_time, 1767225610.0)

        task_span = next(child for child in eval_span.children if child.name == "task")
        self.assertEqual(task_span.event["start_time"], 1767225600.0)
        self.assertEqual(task_span.end_time, 1767225610.0)
        task_child_names = [child.name for child in task_span.children]
        self.assertIn("harbor.trial", task_child_names)
        self.assertIn("tool.inspect", task_child_names)
        self.assertIn("agent.message", task_child_names)
        self.assertIn("agent.tool.shell", task_child_names)
        harbor_span = next(child for child in task_span.children if child.name == "harbor.trial")
        self.assertEqual(harbor_span.event["start_time"], 1767225600.0)
        self.assertEqual(harbor_span.end_time, 1767225610.0)
        message_span = next(child for child in task_span.children if child.name == "agent.message")
        self.assertEqual(message_span.event["start_time"], 1767225602.0)
        self.assertEqual(message_span.end_time, 1767225605.0)

        scorer_span = next(
            child
            for child in eval_span.children
            if child.span_attributes.get("purpose") == "scorer"
        )
        self.assertEqual(scorer_span.span_attributes["type"], "score")
        self.assertEqual(scorer_span.event["scores"], {"Contract": 1.0})


if __name__ == "__main__":
    unittest.main()
