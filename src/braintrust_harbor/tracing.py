"""Import Harbor artifacts into a normalized Braintrust trace contract."""

from __future__ import annotations

import datetime as dt
import inspect
import os
import warnings as py_warnings
from typing import Any

from .artifacts import SuiteArtifactConfig
from .metrics import braintrust_metric_payload, extract_usage_metrics, normalize_usage_metrics


NORMALIZED_TRACE_SCHEMA = "harbor-normalized-trace/v1"


def _current_span() -> Any | None:
    try:
        from braintrust import current_span
    except Exception:
        return None
    try:
        return current_span()
    except Exception:
        return None


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _result_timestamp(output: dict[str, Any], section: str, key: str) -> float | None:
    result = output.get("harbor_result")
    if not isinstance(result, dict):
        return None
    value = result.get(section)
    if isinstance(value, dict):
        return _timestamp(value.get(key))
    return None


def _output_start_time(output: dict[str, Any]) -> float | None:
    return _timestamp(output.get("started_at")) or _result_timestamp(output, "agent_execution", "started_at")


def _output_end_time(output: dict[str, Any]) -> float | None:
    return _timestamp(output.get("finished_at")) or _result_timestamp(output, "agent_execution", "finished_at")


def _step_end_time(steps: list[Any], index: int, fallback: float | None) -> float | None:
    for next_step in steps[index + 1 :]:
        if isinstance(next_step, dict):
            next_timestamp = _timestamp(next_step.get("timestamp"))
            if next_timestamp is not None:
                return next_timestamp
    return fallback


def _observation_output(step: dict[str, Any]) -> Any:
    observation = step.get("observation")
    if not isinstance(observation, dict):
        return None
    results = observation.get("results")
    if not isinstance(results, list):
        return None
    return [
        item.get("content") if isinstance(item, dict) else item
        for item in results
    ]


def _record_warning(warnings: list[str] | None, message: str, exc: Exception | None = None) -> None:
    text = f"{message}: {exc}" if exc is not None else message
    if warnings is not None:
        warnings.append(text)
    if os.getenv("AGENT_TOOLING_EVAL_STRICT_BRAINTRUST_LOGGING") == "1":
        if exc is not None:
            raise exc
        raise RuntimeError(message)
    py_warnings.warn(text, RuntimeWarning, stacklevel=3)


def _safe_log(span: Any, warnings: list[str] | None = None, **payload: Any) -> None:
    try:
        span.log(**{key: value for key, value in payload.items() if value is not None})
    except Exception as exc:
        _record_warning(warnings, "Braintrust span.log failed while importing Harbor trace", exc)


def _metadata(**values: Any) -> dict[str, Any]:
    return {
        "trace_schema": NORMALIZED_TRACE_SCHEMA,
        **{key: value for key, value in values.items() if value is not None},
    }


def _suite_artifact_config(
    output: dict[str, Any],
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> SuiteArtifactConfig:
    if isinstance(suite_artifacts, SuiteArtifactConfig):
        return suite_artifacts
    if isinstance(suite_artifacts, dict):
        return SuiteArtifactConfig.from_dict(suite_artifacts)
    return SuiteArtifactConfig.from_dict(
        output.get("suite_artifacts") if isinstance(output.get("suite_artifacts"), dict) else None
    )


def _command_span_name(command_class: str, suite_config: SuiteArtifactConfig) -> str:
    prefix = suite_config.command_span_prefix.strip(". ")
    return f"{prefix}.{command_class}" if prefix else command_class


def _command_log_rows(output: dict[str, Any], suite_config: SuiteArtifactConfig) -> list[dict[str, Any]]:
    if not suite_config.command_log_key:
        return []
    rows = output.get(suite_config.command_log_key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _iter_step_outputs(output: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    steps = output.get("steps")
    if not isinstance(steps, dict):
        return []
    return [
        (str(name), step)
        for name, step in steps.items()
        if isinstance(step, dict)
    ]


def _step_output(output: dict[str, Any], step_name: str, step: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "job_name": output.get("job_name"),
        "job_dir": output.get("job_dir"),
        "trial_dir": output.get("trial_dir"),
        "agent": output.get("agent"),
        "model": output.get("model"),
        "suite_artifacts": output.get("suite_artifacts"),
        "returncode": output.get("returncode"),
    }
    merged.update(step)
    merged["step_name"] = step_name
    merged["steps"] = {}
    merged["usage_metrics"] = extract_usage_metrics(step)
    return merged


def _start_child(
    parent: Any,
    *,
    name: str,
    span_type: str,
    start_time: float | None = None,
    warnings: list[str] | None = None,
) -> Any | None:
    try:
        return parent.start_span(name=name, type=span_type, start_time=start_time)
    except TypeError as first_exc:
        try:
            return parent.start_span(name=name, span_attributes={"type": span_type}, start_time=start_time)
        except Exception as exc:
            _record_warning(warnings, f"Braintrust start_span failed for {name!r}", exc)
            return None
        finally:
            del first_exc
    except Exception as exc:
        _record_warning(warnings, f"Braintrust start_span failed for {name!r}", exc)
        return None


def _close(span: Any, warnings: list[str] | None = None) -> None:
    try:
        span.end()
    except Exception as first_exc:
        try:
            span.close()
        except Exception as exc:
            _record_warning(warnings, "Braintrust span close failed while importing Harbor trace", exc)
            return
        finally:
            del first_exc


def close_span(span: Any, end_time: float | None = None, warnings: list[str] | None = None) -> None:
    """Close a Braintrust span, preserving imported timing when available."""

    if end_time is None:
        _close(span, warnings=warnings)
        return
    try:
        span.end(end_time=end_time)
    except TypeError as first_exc:
        try:
            span.end(end_time)
        except TypeError:
            try:
                span.end()
            except Exception as exc:
                _record_warning(warnings, "Braintrust span close failed while importing Harbor trace", exc)
        except Exception as exc:
            _record_warning(warnings, "Braintrust span close failed while importing Harbor trace", exc)
        finally:
            del first_exc
    except Exception as first_exc:
        try:
            span.close()
        except Exception as exc:
            _record_warning(warnings, "Braintrust span close failed while importing Harbor trace", exc)
        finally:
            del first_exc


def _log_harbor_result(
    parent: Any,
    output: dict[str, Any],
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> None:
    suite_config = _suite_artifact_config(output, suite_artifacts)
    result = output.get("harbor_result")
    exception_info = result.get("exception_info") if isinstance(result, dict) else None
    usage_metrics = extract_usage_metrics(output)
    command_rows = _command_log_rows(output, suite_config)
    metadata = _metadata(
        normalized_kind="harness_run",
        agent=output.get("agent"),
        model=output.get("model"),
        job_name=output.get("job_name"),
        job_dir=output.get("job_dir"),
        trial_dir=output.get("trial_dir"),
        returncode=output.get("returncode"),
        duration_sec=output.get("duration_sec"),
        command_count=len(command_rows),
        usage_metrics=usage_metrics or None,
        exception_type=exception_info.get("exception_type") if isinstance(exception_info, dict) else None,
    )
    harbor_span = _start_child(
        parent,
        name="harbor.trial",
        span_type="function",
        start_time=_output_start_time(output),
        warnings=warnings,
    )
    if harbor_span is None:
        return
    try:
        _safe_log(
            harbor_span,
            warnings,
            input=output.get("command"),
            output={
                "stdout": output.get("stdout"),
                "stderr": output.get("stderr"),
                "reward": output.get("reward"),
                "result": result,
            },
            metadata=metadata,
            metrics=braintrust_metric_payload(usage_metrics) or None,
            error=exception_info or output.get("error") or output.get("exception_text") or None,
        )
    finally:
        close_span(harbor_span, end_time=_output_end_time(output), warnings=warnings)


def _log_command_spans(
    parent: Any,
    output: dict[str, Any],
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> None:
    suite_config = _suite_artifact_config(output, suite_artifacts)
    for index, row in enumerate(_command_log_rows(output, suite_config), start=1):
        command_class = str(row.get("command_class") or "command")
        start_time = _timestamp(row.get("timestamp")) or _timestamp(row.get("started_at"))
        command_span = _start_child(
            parent,
            name=_command_span_name(command_class, suite_config),
            span_type="tool",
            start_time=start_time,
            warnings=warnings,
        )
        if command_span is None:
            continue
        try:
            _safe_log(
                command_span,
                warnings,
                input=row.get("argv"),
                output=row.get("stdout") or row.get("result"),
                metadata=_metadata(
                    **{
                        **row,
                        "normalized_kind": "command_log_entry",
                        "sequence": index,
                        "tool_name": suite_config.command_tool_name or suite_config.command_span_prefix or "command",
                        "command_class": command_class,
                    }
                ),
            )
        finally:
            close_span(
                command_span,
                end_time=_timestamp(row.get("finished_at")) or start_time,
                warnings=warnings,
            )


def _log_trajectory_spans(parent: Any, output: dict[str, Any], warnings: list[str] | None = None) -> None:
    trajectory = output.get("trajectory")
    if not isinstance(trajectory, dict):
        return
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        return
    max_steps = int(os.getenv("HARBOR_TRACE_MAX_STEPS", "200"))
    bounded_steps = steps[:max_steps]
    agent_end_time = _result_timestamp(output, "agent_execution", "finished_at") or _output_end_time(output)
    for index, step in enumerate(bounded_steps):
        if not isinstance(step, dict):
            continue
        step_usage_metrics = normalize_usage_metrics(step.get("metrics"))
        tool_calls = step.get("tool_calls")
        source = step.get("source")
        start_time = _timestamp(step.get("timestamp"))
        end_time = _step_end_time(bounded_steps, index, agent_end_time) or start_time
        if source == "agent":
            message_span = _start_child(
                parent,
                name="agent.message",
                span_type="llm",
                start_time=start_time,
                warnings=warnings,
            )
            if message_span is not None:
                try:
                    _safe_log(
                        message_span,
                        warnings,
                        output=step.get("message"),
                        metadata=_metadata(
                            normalized_kind="agent_message",
                            step_id=step.get("step_id"),
                            source=source,
                            model_name=step.get("model_name"),
                            tool_calls=tool_calls,
                            metrics=step.get("metrics"),
                            usage_metrics=step_usage_metrics or None,
                            extra=step.get("extra"),
                            trajectory_session_id=trajectory.get("session_id"),
                            agent=trajectory.get("agent"),
                        ),
                        metrics=braintrust_metric_payload(step_usage_metrics) or None,
                    )
                finally:
                    close_span(message_span, end_time=end_time, warnings=warnings)

            if isinstance(tool_calls, list):
                observation_output = _observation_output(step)
                for call_index, tool_call in enumerate(tool_calls, start=1):
                    if not isinstance(tool_call, dict):
                        continue
                    tool_name = str(tool_call.get("function_name") or "tool")
                    tool_span = _start_child(
                        parent,
                        name=f"agent.tool.{tool_name}",
                        span_type="tool",
                        start_time=start_time,
                        warnings=warnings,
                    )
                    if tool_span is None:
                        continue
                    try:
                        _safe_log(
                            tool_span,
                            warnings,
                            input=tool_call.get("arguments"),
                            output=observation_output,
                            metadata=_metadata(
                                normalized_kind="agent_tool_call",
                                step_id=step.get("step_id"),
                                source=source,
                                model_name=step.get("model_name"),
                                tool_call=tool_call,
                                tool_call_index=call_index,
                                extra=step.get("extra"),
                                trajectory_session_id=trajectory.get("session_id"),
                                agent=trajectory.get("agent"),
                            ),
                        )
                    finally:
                        close_span(tool_span, end_time=end_time, warnings=warnings)
            continue

        context_span = _start_child(
            parent,
            name="agent.context",
            span_type="task",
            start_time=start_time,
            warnings=warnings,
        )
        if context_span is None:
            continue
        try:
            _safe_log(
                context_span,
                warnings,
                input=step.get("message"),
                output=step.get("message"),
                metadata=_metadata(
                    normalized_kind="agent_context",
                    step_id=step.get("step_id"),
                    source=source,
                    metrics=step.get("metrics"),
                    usage_metrics=step_usage_metrics or None,
                    extra=step.get("extra"),
                    trajectory_session_id=trajectory.get("session_id"),
                    agent=trajectory.get("agent"),
                ),
            )
        finally:
            close_span(context_span, end_time=end_time, warnings=warnings)


def _log_step_spans(
    parent: Any,
    output: dict[str, Any],
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> None:
    suite_config = _suite_artifact_config(output, suite_artifacts)
    for step_name, step in _iter_step_outputs(output):
        merged = _step_output(output, step_name, step)
        usage_metrics = extract_usage_metrics(merged)
        step_span = _start_child(
            parent,
            name=f"harbor.step.{step_name}",
            span_type="function",
            start_time=_output_start_time(merged),
            warnings=warnings,
        )
        if step_span is None:
            continue
        try:
            _safe_log(
                step_span,
                warnings,
                output={
                    "reward": merged.get("reward"),
                    "reward_details": merged.get("reward_details"),
                    "artifact_manifest": merged.get("artifact_manifest"),
                    "artifacts": merged.get("artifacts"),
                },
                metadata=_metadata(
                    normalized_kind="harness_step",
                    step_name=step_name,
                    runtime_dir=merged.get("runtime_dir"),
                    usage_metrics=usage_metrics or None,
                ),
                metrics=braintrust_metric_payload(usage_metrics) or None,
            )
            _log_command_spans(step_span, merged, suite_artifacts=suite_config, warnings=warnings)
            _log_trajectory_spans(step_span, merged, warnings=warnings)
        finally:
            close_span(step_span, end_time=_output_end_time(merged), warnings=warnings)


def _append_step_records(
    records: list[dict[str, Any]],
    output: dict[str, Any],
    suite_config: SuiteArtifactConfig,
) -> None:
    for step_name, step in _iter_step_outputs(output):
        step_records = normalized_trace_span_records(
            _step_output(output, step_name, step),
            suite_artifacts=suite_config,
        )
        for record in step_records:
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            metadata = {**metadata, "step_name": step_name}
            if record.get("name") == "harbor.trial":
                record["name"] = f"harbor.step.{step_name}"
                record["span_attributes"] = {
                    "name": record["name"],
                    "type": record.get("type", "function"),
                }
                metadata["normalized_kind"] = "harness_step"
                metadata["runtime_dir"] = step.get("runtime_dir")
            record["metadata"] = metadata
            records.append(record)


def normalized_trace_span_records(
    output: dict[str, Any],
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build lightweight span records matching the normalized Braintrust trace."""

    suite_config = _suite_artifact_config(output, suite_artifacts)
    records: list[dict[str, Any]] = []
    result = output.get("harbor_result")
    exception_info = result.get("exception_info") if isinstance(result, dict) else None
    usage_metrics = extract_usage_metrics(output)
    command_rows = _command_log_rows(output, suite_config)
    harbor_metadata = _metadata(
        normalized_kind="harness_run",
        agent=output.get("agent"),
        model=output.get("model"),
        job_name=output.get("job_name"),
        job_dir=output.get("job_dir"),
        trial_dir=output.get("trial_dir"),
        returncode=output.get("returncode"),
        duration_sec=output.get("duration_sec"),
        command_count=len(command_rows),
        usage_metrics=usage_metrics or None,
        exception_type=exception_info.get("exception_type") if isinstance(exception_info, dict) else None,
    )
    records.append(
        {
            "name": "harbor.trial",
            "type": "function",
            "span_attributes": {"name": "harbor.trial", "type": "function"},
            "input": output.get("command"),
            "output": {
                "stdout": output.get("stdout"),
                "stderr": output.get("stderr"),
                "reward": output.get("reward"),
                "result": result,
            },
            "metadata": harbor_metadata,
            "metrics": braintrust_metric_payload(usage_metrics) or None,
            "error": exception_info or output.get("error") or output.get("exception_text") or None,
        }
    )

    for index, row in enumerate(command_rows, start=1):
        command_class = str(row.get("command_class") or "command")
        name = _command_span_name(command_class, suite_config)
        records.append(
            {
                "name": name,
                "type": "tool",
                "span_attributes": {"name": name, "type": "tool"},
                "input": row.get("argv"),
                "output": row.get("stdout") or row.get("result"),
                "metadata": _metadata(
                    **{
                        **row,
                        "normalized_kind": "command_log_entry",
                        "sequence": index,
                        "tool_name": suite_config.command_tool_name or suite_config.command_span_prefix or "command",
                        "command_class": command_class,
                    }
                ),
            }
        )

    trajectory = output.get("trajectory")
    if not isinstance(trajectory, dict):
        _append_step_records(records, output, suite_config)
        return records
    steps = trajectory.get("steps")
    if not isinstance(steps, list):
        _append_step_records(records, output, suite_config)
        return records
    max_steps = int(os.getenv("HARBOR_TRACE_MAX_STEPS", "200"))
    for step in steps[:max_steps]:
        if not isinstance(step, dict):
            continue
        step_usage_metrics = normalize_usage_metrics(step.get("metrics"))
        tool_calls = step.get("tool_calls")
        source = step.get("source")
        if source == "agent":
            records.append(
                {
                    "name": "agent.message",
                    "type": "llm",
                    "span_attributes": {"name": "agent.message", "type": "llm"},
                    "output": step.get("message"),
                    "metadata": _metadata(
                        normalized_kind="agent_message",
                        step_id=step.get("step_id"),
                        source=source,
                        model_name=step.get("model_name"),
                        tool_calls=tool_calls,
                        metrics=step.get("metrics"),
                        usage_metrics=step_usage_metrics or None,
                        extra=step.get("extra"),
                        trajectory_session_id=trajectory.get("session_id"),
                        agent=trajectory.get("agent"),
                    ),
                    "metrics": braintrust_metric_payload(step_usage_metrics) or None,
                }
            )
            if isinstance(tool_calls, list):
                observation_output = _observation_output(step)
                for call_index, tool_call in enumerate(tool_calls, start=1):
                    if not isinstance(tool_call, dict):
                        continue
                    tool_name = str(tool_call.get("function_name") or "tool")
                    name = f"agent.tool.{tool_name}"
                    records.append(
                        {
                            "name": name,
                            "type": "tool",
                            "span_attributes": {"name": name, "type": "tool"},
                            "input": tool_call.get("arguments"),
                            "output": observation_output,
                            "metadata": _metadata(
                                normalized_kind="agent_tool_call",
                                step_id=step.get("step_id"),
                                source=source,
                                model_name=step.get("model_name"),
                                tool_call=tool_call,
                                tool_call_index=call_index,
                                extra=step.get("extra"),
                                trajectory_session_id=trajectory.get("session_id"),
                                agent=trajectory.get("agent"),
                            ),
                        }
                    )
            continue

        records.append(
            {
                "name": "agent.context",
                "type": "task",
                "span_attributes": {"name": "agent.context", "type": "task"},
                "input": step.get("message"),
                "output": step.get("message"),
                "metadata": _metadata(
                    normalized_kind="agent_context",
                    step_id=step.get("step_id"),
                    source=source,
                    metrics=step.get("metrics"),
                    usage_metrics=step_usage_metrics or None,
                    extra=step.get("extra"),
                    trajectory_session_id=trajectory.get("session_id"),
                    agent=trajectory.get("agent"),
                ),
            }
        )
    _append_step_records(records, output, suite_config)
    return records


def log_harbor_trace(
    output: dict[str, Any],
    parent: Any | None = None,
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> list[str]:
    """Best-effort import of Harbor artifacts into the normalized trace surface."""

    warnings: list[str] = []
    parent = parent or _current_span()
    if parent is None:
        return warnings
    _log_harbor_result(parent, output, suite_artifacts=suite_artifacts, warnings=warnings)
    _log_command_spans(parent, output, suite_artifacts=suite_artifacts, warnings=warnings)
    _log_trajectory_spans(parent, output, warnings=warnings)
    _log_step_spans(parent, output, suite_artifacts=suite_artifacts, warnings=warnings)
    return warnings


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
