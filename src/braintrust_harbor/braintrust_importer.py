"""Import Harbor job outputs into Braintrust experiments."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import traceback
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .artifacts import SuiteArtifactConfig, load_harbor_job_outputs
from .metrics import braintrust_metric_payload
from .tracing import close_span, log_harbor_trace, normalized_trace_span_records


Scorer = Callable[..., Any]
ScoreValue = float | None


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


class TraceLike(Protocol):
    """Scorer-facing subset shared by Braintrust LocalTrace and offline imports."""

    def get_configuration(self) -> dict[str, str]:
        ...

    async def get_spans(self, span_type: list[str] | None = None) -> list[Any]:
        ...

    async def get_thread(self, options: Any = None) -> list[Any]:
        ...


@dataclass(frozen=True)
class _OfflineSpanData:
    """Fallback for Braintrust's SpanData when the SDK is not importable."""

    input: Any = None
    output: Any = None
    metadata: dict[str, Any] | None = None
    span_id: str | None = None
    span_parents: list[str] | None = None
    span_attributes: dict[str, Any] | None = None
    name: str | None = None
    type: str | None = None
    error: Any = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


def _span_from_record(record: Mapping[str, Any]) -> Any:
    span_attributes = record.get("span_attributes")
    span_attributes = span_attributes if isinstance(span_attributes, dict) else {}
    metadata = record.get("metadata")
    payload = {
        "input": record.get("input"),
        "output": record.get("output"),
        "metadata": metadata if isinstance(metadata, dict) else None,
        "span_id": record.get("span_id") if isinstance(record.get("span_id"), str) else None,
        "span_parents": record.get("span_parents") if isinstance(record.get("span_parents"), list) else None,
        "span_attributes": span_attributes,
        "name": str(record.get("name") or span_attributes.get("name") or ""),
        "type": str(record.get("type") or span_attributes.get("type") or ""),
        "error": record.get("error"),
        "metrics": record.get("metrics") if isinstance(record.get("metrics"), dict) else None,
    }
    try:
        from braintrust.trace import SpanData
    except Exception:
        return _OfflineSpanData(**payload)
    return SpanData(**payload)


class ImportedTrace(dict[str, Any]):
    """Local trace adapter for scoring imported Harbor artifacts.

    Braintrust's SDK supplies a LocalTrace during normal `Eval(...)` execution.
    The importer is not running the task through `Eval(...)`; it is reading an
    already-finished Harbor job and then constructing the Braintrust row. This
    adapter gives trace-level scorers the same core methods over normalized
    Harbor span records. It is an offline trace view, not a Braintrust
    LocalTrace backed by a live experiment object.
    """

    def __init__(self, spans: list[dict[str, Any]], *, job_dir: str | None = None, trial_dir: str | None = None):
        configuration = {
            key: value
            for key, value in {
                "object_type": "offline_harbor_job",
                "object_id": job_dir,
                "root_span_id": trial_dir,
            }.items()
            if value is not None
        }
        super().__init__({"trace_ref": configuration})
        self._spans = [_span_from_record(span) for span in spans]
        self._configuration = {
            key: value
            for key, value in configuration.items()
            if value is not None
        }

    def get_configuration(self) -> dict[str, str]:
        return dict(self._configuration)

    async def get_spans(self, span_type: list[str] | None = None) -> list[Any]:
        if not span_type:
            return list(self._spans)
        allowed = set(span_type)
        return [
            span
            for span in self._spans
            if ((span.span_attributes or {}).get("type") or span.type) in allowed
        ]

    async def get_thread(self, _options: Any = None) -> list[Any]:
        thread: list[dict[str, Any]] = []
        for span in self._spans:
            metadata = getattr(span, "metadata", None)
            metadata = metadata if isinstance(metadata, dict) else {}
            kind = metadata.get("normalized_kind")
            if kind == "agent_context":
                thread.append({"role": "user", "content": getattr(span, "input", None), "metadata": metadata})
            elif kind == "agent_message":
                thread.append({"role": "assistant", "content": getattr(span, "output", None), "metadata": metadata})
            elif kind == "agent_tool_call":
                thread.append({"role": "tool", "content": getattr(span, "output", None), "metadata": metadata})
        return thread


@dataclass(frozen=True)
class ScorerArgs:
    input: Any
    output: Any
    expected: Any | None = None
    metadata: dict[str, Any] | None = None
    trace: TraceLike | None = None


@dataclass
class BraintrustImportResult:
    project: str
    experiment_name: str
    job_dir: str
    uploaded: bool
    row_count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    experiment_id: str | None = None
    summary: Any | None = None
    preview_path: str | None = None


def _callable_name(obj: Any, idx: int, fallback_prefix: str = "scorer") -> str:
    if hasattr(obj, "_name") and callable(obj._name):
        name = str(obj._name())
    elif hasattr(obj, "__name__"):
        name = str(obj.__name__)
    else:
        name = type(obj).__name__
    return f"{fallback_prefix}_{idx}" if name == "<lambda>" else name


def _prepare_scorer(scorer: Scorer) -> Scorer:
    if inspect.isclass(scorer) and (
        hasattr(scorer, "eval")
        or hasattr(scorer, "eval_async")
        or hasattr(scorer, "_run_eval_sync")
        or hasattr(scorer, "_run_eval_async")
    ):
        return scorer()
    return scorer


def _scorer_kwargs_for_signature(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs

    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    remaining = dict(kwargs)
    final_kwargs: dict[str, Any] = {}

    for name, param in signature.parameters.items():
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if name in remaining:
            final_kwargs[name] = remaining.pop(name)
        elif name == "scorer_args":
            final_kwargs[name] = ScorerArgs(**kwargs)
        elif param.default is not inspect.Parameter.empty:
            final_kwargs[name] = param.default
        elif param.default is inspect.Parameter.empty and remaining:
            fallback_key = next(iter(remaining))
            final_kwargs[name] = remaining.pop(fallback_key)

    if accepts_kwargs:
        final_kwargs.update(remaining)
    return final_kwargs


async def _call_scorer(
    scorer: Scorer,
    scorer_name: str,
    *,
    input_value: Any,
    output: Any,
    expected: Any,
    metadata: dict[str, Any],
    trace: TraceLike,
) -> list[dict[str, Any]]:
    score_fn = getattr(scorer, "eval_async", scorer)
    scorer_kwargs = _scorer_kwargs_for_signature(
        score_fn,
        {
            "input": input_value,
            "output": output,
            "expected": expected,
            "metadata": metadata,
            "trace": trace,
        },
    )
    value = score_fn(**scorer_kwargs)
    if inspect.isawaitable(value):
        value = await value
    if isinstance(value, list | tuple):
        return [_coerce_score_result(item, scorer_name) for item in value]
    return [_coerce_score_result(value, scorer_name)]


def _score_like_dict(value: Any) -> dict[str, Any] | None:
    if all(hasattr(value, attr) for attr in ("name", "score", "metadata", "as_dict")):
        raw = value.as_dict()
        return dict(raw) if isinstance(raw, Mapping) else None
    return None


def _validate_score_result(value: Mapping[str, Any]) -> dict[str, Any]:
    name = str(value.get("name") or "")
    if not name:
        raise ValueError(f"Score result must include a non-empty name. Got: {value}")
    raw_score = value.get("score")
    if isinstance(raw_score, bool):
        score: ScoreValue = 1.0 if raw_score else 0.0
    elif raw_score is None:
        score = None
    elif isinstance(raw_score, int | float):
        score = float(raw_score)
    else:
        raise ValueError(f"Score {name!r} must be numeric or None. Got: {raw_score!r}")
    if score is not None and not 0.0 <= score <= 1.0:
        raise ValueError(f"Score {name!r} must be between 0 and 1. Got: {score}")
    metadata = value.get("metadata")
    return {
        "name": name,
        "score": score,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _coerce_score_result(value: Any, scorer_name: str) -> dict[str, Any]:
    score_like = _score_like_dict(value)
    if score_like is not None:
        return _validate_score_result(score_like)
    if isinstance(value, dict):
        return _validate_score_result(value)
    if value is None:
        return {"name": scorer_name, "score": None, "metadata": {}}
    if isinstance(value, bool):
        return {"name": scorer_name, "score": 1.0 if value else 0.0, "metadata": {}}
    if isinstance(value, int | float):
        return _validate_score_result({"name": scorer_name, "score": value})
    raise ValueError(f"Scorer {scorer_name!r} returned an unsupported score value: {value!r}")


def _run_coroutine_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def score_trial(
    output: Any,
    *,
    input: Any = None,
    expected: Any = None,
    metadata: dict[str, Any] | None = None,
    scorers: Iterable[Scorer] = (),
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> tuple[dict[str, ScoreValue], dict[str, Any]]:
    output_for_trace = output if isinstance(output, dict) else {}
    spans = normalized_trace_span_records(output_for_trace, suite_artifacts=suite_artifacts)
    trace = ImportedTrace(
        spans,
        job_dir=output_for_trace.get("job_dir"),
        trial_dir=output_for_trace.get("trial_dir"),
    )
    scorer_list = list(scorers)
    scorer_metadata = metadata or {}

    async def run_all() -> list[dict[str, Any]]:
        evaluations: list[dict[str, Any]] = []
        for idx, raw_scorer in enumerate(scorer_list):
            scorer = _prepare_scorer(raw_scorer)
            scorer_name = _callable_name(scorer, idx)
            try:
                score_results = await _call_scorer(
                    scorer,
                    scorer_name,
                    input_value=input,
                    output=output,
                    expected=expected,
                    metadata=scorer_metadata,
                    trace=trace,
                )
                evaluations.append({"name": scorer_name, "scores": score_results})
            except Exception:
                evaluations.append(
                    {
                        "name": scorer_name,
                        "scores": [],
                        "error": traceback.format_exc(),
                    }
                )
        return evaluations

    scorer_evaluations = _run_coroutine_sync(run_all()) if scorer_list else []
    scores: dict[str, ScoreValue] = {}
    errors: dict[str, str] = {}
    for evaluation in scorer_evaluations:
        scorer_name = str(evaluation.get("name") or "scorer")
        if evaluation.get("error"):
            errors[scorer_name] = str(evaluation["error"])
        for score in evaluation.get("scores") or []:
            if not isinstance(score, dict):
                continue
            scores[str(score["name"])] = score.get("score")
    details: dict[str, Any] = {"scorers": scorer_evaluations}
    if errors:
        details["errors"] = errors
    return scores, details


def _base_row_metadata(output: dict[str, Any]) -> dict[str, Any]:
    task_metadata = output.get("task_metadata") if isinstance(output.get("task_metadata"), dict) else {}
    suite_metadata = task_metadata.get("metadata") if isinstance(task_metadata.get("metadata"), dict) else {}
    return {
        **suite_metadata,
        "harness": "harbor",
        "job_name": output.get("job_name"),
        "job_dir": output.get("job_dir"),
        "trial_dir": output.get("trial_dir"),
        "task_name": output.get("task_name"),
        "agent": output.get("agent"),
        "agent_import_path": output.get("agent_import_path"),
        "model": output.get("model"),
        "usage_metrics": output.get("usage_metrics"),
    }


def _row_metadata(output: dict[str, Any], score_details: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        **_base_row_metadata(output),
        "score_details": score_details,
    }
    if isinstance(score_details.get("errors"), dict):
        metadata["scorer_errors"] = score_details["errors"]
    return {key: value for key, value in metadata.items() if value is not None}


def _row_output(output: dict[str, Any], suite_config: SuiteArtifactConfig) -> dict[str, Any]:
    suite_artifacts = {
        artifact.key: output.get(artifact.key)
        for artifact in suite_config.artifacts
        if artifact.key in output
    }
    return {
        **suite_artifacts,
        "reward": output.get("reward"),
        "reward_details": output.get("reward_details"),
        "usage_metrics": output.get("usage_metrics"),
        "artifact_manifest": output.get("artifact_manifest"),
        "artifacts": output.get("artifacts"),
        "harbor_result": output.get("harbor_result"),
        "exception_text": output.get("exception_text"),
        "trial_log": output.get("trial_log"),
        "steps": _row_steps(output, suite_config),
    }


def _row_steps(output: dict[str, Any], suite_config: SuiteArtifactConfig) -> dict[str, Any]:
    raw_steps = output.get("steps")
    if not isinstance(raw_steps, dict):
        return {}

    steps: dict[str, Any] = {}
    for name, step in raw_steps.items():
        if not isinstance(step, dict):
            continue
        suite_artifacts = {
            artifact.key: step.get(artifact.key)
            for artifact in suite_config.artifacts
            if artifact.key in step
        }
        steps[str(name)] = {
            **suite_artifacts,
            "runtime_dir": step.get("runtime_dir"),
            "reward": step.get("reward"),
            "reward_details": step.get("reward_details"),
            "usage_metrics": step.get("usage_metrics"),
            "artifact_manifest": step.get("artifact_manifest"),
            "artifacts": step.get("artifacts"),
        }
    return steps


def _metadata_without_score_details(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"score_details", "scorer_errors"}
    }


def _start_scorer_span(root: Any, name: str, row: dict[str, Any]) -> Any:
    logged_input = {
        "input": row["input"],
        "output": row["output"],
        "expected": row["expected"],
        "metadata": _metadata_without_score_details(row["metadata"]),
    }
    return root.start_span(
        name=name,
        span_attributes={"type": "score", "purpose": "scorer"},
        input=logged_input,
    )


def _log_scorer_spans(root: Any, row: dict[str, Any]) -> None:
    score_details = row["metadata"].get("score_details")
    if not isinstance(score_details, dict):
        return
    for evaluation in score_details.get("scorers") or []:
        if not isinstance(evaluation, dict):
            continue
        scorer_name = str(evaluation.get("name") or "scorer")
        scorer_span = _start_scorer_span(root, scorer_name, row)
        try:
            error = evaluation.get("error")
            if error:
                scorer_span.log(error=error, metadata={"scorer_error": True})
                continue

            score_results = [
                score
                for score in evaluation.get("scores") or []
                if isinstance(score, dict)
            ]
            score_map = {str(score["name"]): score.get("score") for score in score_results}
            if len(score_results) == 1:
                output = {
                    key: value
                    for key, value in score_results[0].items()
                    if key not in {"name", "metadata"}
                }
                metadata = score_results[0].get("metadata")
                metadata = metadata if isinstance(metadata, dict) else {}
            else:
                output = {
                    str(score["name"]): {
                        key: value
                        for key, value in score.items()
                        if key not in {"name", "metadata"}
                    }
                    for score in score_results
                }
                metadata = {
                    str(score["name"]): score.get("metadata")
                    for score in score_results
                    if isinstance(score.get("metadata"), dict)
                }
            scorer_span.log(output=output, metadata=metadata, scores=score_map)
        finally:
            scorer_span.end()


def import_harbor_job_to_braintrust(
    *,
    job_dir: str,
    project: str,
    experiment_name: str,
    scorers: Iterable[Scorer],
    upload: bool,
    metadata: dict[str, Any] | None = None,
    preview_path: str | None = None,
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> BraintrustImportResult:
    suite_config = (
        suite_artifacts
        if isinstance(suite_artifacts, SuiteArtifactConfig)
        else SuiteArtifactConfig.from_dict(suite_artifacts)
    )
    outputs = load_harbor_job_outputs(job_dir, suite_artifacts=suite_config)
    rows: list[dict[str, Any]] = []
    for output in outputs:
        expected = output.get("expected")
        input_value = output.get("eval_input")
        scorer_metadata = {
            key: value
            for key, value in _base_row_metadata(output).items()
            if value is not None
        }
        scores, score_details = score_trial(
            output,
            input=input_value,
            expected=expected,
            metadata=scorer_metadata,
            scorers=scorers,
            suite_artifacts=suite_config,
        )
        row = {
            "input": input_value,
            "expected": expected,
            "output": _row_output(output, suite_config),
            "scores": scores,
            "metadata": _row_metadata(output, score_details),
        }
        rows.append(row)

    result = BraintrustImportResult(
        project=project,
        experiment_name=experiment_name,
        job_dir=job_dir,
        uploaded=upload,
        row_count=len(rows),
        rows=rows,
    )

    if not upload:
        preview = Path(preview_path) if preview_path else Path(job_dir) / "braintrust-import-preview.json"
        preview.write_text(json.dumps({"project": project, "experiment_name": experiment_name, "rows": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result.preview_path = str(preview)
        return result

    from braintrust import init

    experiment = init(
        project=project,
        experiment=experiment_name,
        description="Harbor coding-agent job imported into Braintrust.",
        metadata=metadata or {},
    )
    result.experiment_id = getattr(experiment, "id", None)

    for row, output in zip(rows, outputs, strict=False):
        start_time = _timestamp(output.get("started_at"))
        end_time = _timestamp(output.get("finished_at"))
        root = experiment.start_span(
            name="eval",
            span_attributes={"type": "eval"},
            start_time=start_time,
            input=row["input"],
            output=row["output"],
            expected=row["expected"],
            scores=row["scores"],
            metadata=row["metadata"],
            metrics=braintrust_metric_payload(output.get("usage_metrics")) or None,
        )
        try:
            task_span = root.start_span(
                name="task",
                span_attributes={"type": "task"},
                start_time=start_time,
                input=row["input"],
            )
            try:
                task_span.log(
                    input=row["input"],
                    output=row["output"],
                    metrics=braintrust_metric_payload(output.get("usage_metrics")) or None,
                )
                trace_warnings = log_harbor_trace(output, parent=task_span, suite_artifacts=suite_config)
                if trace_warnings:
                    root.log(
                        metadata={
                            **row["metadata"],
                            "braintrust_import_warnings": trace_warnings,
                        }
                    )
            finally:
                close_span(task_span, end_time=end_time)
            _log_scorer_spans(root, row)
        finally:
            close_span(root, end_time=end_time)

    result.summary = experiment.summarize()
    return result
