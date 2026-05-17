"""Token and cost metric normalization for Harbor trajectories."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_INPUT_KEYS = {
    "input_tokens",
    "prompt_tokens",
    "n_input_tokens",
    "total_prompt_tokens",
}
_OUTPUT_KEYS = {
    "output_tokens",
    "completion_tokens",
    "n_output_tokens",
    "total_completion_tokens",
}
_CACHE_KEYS = {
    "cache_tokens",
    "cached_tokens",
    "cached_input_tokens",
    "n_cache_tokens",
    "total_cached_tokens",
}
_TOTAL_KEYS = {
    "tokens",
    "total_tokens",
    "n_tokens",
}
_COST_KEYS = {
    "cost",
    "cost_usd",
    "estimated_cost",
    "estimated_cost_usd",
    "total_cost",
    "total_cost_usd",
}
_REASONING_KEYS = {
    "reasoning_tokens",
    "reasoning_output_tokens",
}
_USAGE_KEYS = _INPUT_KEYS | _OUTPUT_KEYS | _CACHE_KEYS | _TOTAL_KEYS | _COST_KEYS | _REASONING_KEYS


def _key(value: Any) -> str:
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", str(value))
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _add(target: dict[str, float], key: str, value: float) -> None:
    target[key] = target.get(key, 0.0) + value


def normalize_usage_metrics(value: Mapping[str, Any] | None) -> dict[str, float]:
    """Normalize one flat metrics object into canonical token/cost fields."""

    if not isinstance(value, Mapping):
        return {}

    metrics: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        number = _number(raw_value)
        if number is None:
            continue
        key = _key(raw_key)
        if key in _INPUT_KEYS:
            _add(metrics, "input_tokens", number)
        elif key in _OUTPUT_KEYS:
            _add(metrics, "output_tokens", number)
        elif key in _CACHE_KEYS:
            _add(metrics, "cache_tokens", number)
        elif key in _TOTAL_KEYS:
            _add(metrics, "total_tokens", number)
        elif key in _COST_KEYS:
            _add(metrics, "cost_usd", number)
        elif key in _REASONING_KEYS:
            _add(metrics, "reasoning_tokens", number)

    return finalize_usage_metrics(metrics)


def finalize_usage_metrics(metrics: Mapping[str, Any] | None) -> dict[str, float]:
    """Return canonical metrics with a derived total when needed."""

    if not isinstance(metrics, Mapping):
        return {}

    finalized: dict[str, float] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_tokens",
        "total_tokens",
        "cost_usd",
        "reasoning_tokens",
    ):
        number = _number(metrics.get(key))
        if number is not None:
            finalized[key] = number

    if "total_tokens" not in finalized:
        total = finalized.get("input_tokens", 0.0) + finalized.get("output_tokens", 0.0)
        if total:
            finalized["total_tokens"] = total

    return {
        key: int(value) if float(value).is_integer() else round(value, 6)
        for key, value in finalized.items()
    }


def _usage_from_steps(steps: Any) -> dict[str, float]:
    if not isinstance(steps, list):
        return {}

    totals: dict[str, float] = {}
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        step_metrics = normalize_usage_metrics(step.get("metrics"))
        for key, value in step_metrics.items():
            _add(totals, key, float(value))
    return finalize_usage_metrics(totals)


def _scan_metric_groups(value: Any, *, depth: int = 0) -> dict[str, float]:
    """Fallback scanner for Harbor result objects without a trajectory."""

    if depth > 8:
        return {}
    totals: dict[str, float] = {}
    if isinstance(value, Mapping):
        direct_keys = {_key(key) for key in value}
        if direct_keys & _USAGE_KEYS:
            return normalize_usage_metrics(value)
        for child in value.values():
            child_metrics = _scan_metric_groups(child, depth=depth + 1)
            for key, metric_value in child_metrics.items():
                _add(totals, key, float(metric_value))
    elif isinstance(value, list):
        for child in value[:500]:
            child_metrics = _scan_metric_groups(child, depth=depth + 1)
            for key, metric_value in child_metrics.items():
                _add(totals, key, float(metric_value))
    return finalize_usage_metrics(totals)


def _merge_missing(primary: dict[str, float], fallback: dict[str, float]) -> dict[str, float]:
    merged = dict(primary)
    for key, value in fallback.items():
        if key not in merged:
            merged[key] = value
    return finalize_usage_metrics(merged)


def _usage_from_trial_steps(steps: Any) -> dict[str, float]:
    if not isinstance(steps, Mapping):
        return {}

    totals: dict[str, float] = {}
    for step in steps.values():
        if not isinstance(step, Mapping):
            continue
        step_metrics = extract_usage_metrics(step)
        for key, value in step_metrics.items():
            _add(totals, key, float(value))
    return finalize_usage_metrics(totals)


def extract_usage_metrics(output: Mapping[str, Any] | None) -> dict[str, float]:
    """Extract canonical usage metrics from a Harbor eval output."""

    if not isinstance(output, Mapping):
        return {}

    existing = normalize_usage_metrics(output.get("usage_metrics"))
    if existing:
        return existing

    trajectory = output.get("trajectory")
    metrics: dict[str, float] = {}
    if isinstance(trajectory, Mapping):
        raw_final_metrics = trajectory.get("final_metrics")
        final_metrics = normalize_usage_metrics(raw_final_metrics)
        if final_metrics and isinstance(raw_final_metrics, Mapping):
            final_metrics = _merge_missing(
                final_metrics,
                normalize_usage_metrics(raw_final_metrics.get("extra")),
            )
        if final_metrics:
            metrics = final_metrics
        else:
            metrics = _usage_from_steps(trajectory.get("steps"))

    if not metrics:
        metrics = _usage_from_trial_steps(output.get("steps"))

    fallback = _scan_metric_groups(output.get("harbor_result"))
    if metrics:
        return _merge_missing(metrics, fallback)
    return fallback


def braintrust_metric_payload(metrics: Mapping[str, Any] | None) -> dict[str, float]:
    """Map canonical usage metrics to Braintrust's conventional metric names."""

    canonical = normalize_usage_metrics(metrics)
    if not canonical:
        canonical = finalize_usage_metrics(metrics)
    payload: dict[str, float] = {}
    if "input_tokens" in canonical:
        payload["prompt_tokens"] = canonical["input_tokens"]
        payload["input_tokens"] = canonical["input_tokens"]
    if "output_tokens" in canonical:
        payload["completion_tokens"] = canonical["output_tokens"]
        payload["output_tokens"] = canonical["output_tokens"]
    if "total_tokens" in canonical:
        payload["tokens"] = canonical["total_tokens"]
        payload["total_tokens"] = canonical["total_tokens"]
    if "cache_tokens" in canonical:
        payload["cached_tokens"] = canonical["cache_tokens"]
    if "cost_usd" in canonical:
        payload["estimated_cost"] = canonical["cost_usd"]
        payload["cost_usd"] = canonical["cost_usd"]
    if "reasoning_tokens" in canonical:
        payload["reasoning_tokens"] = canonical["reasoning_tokens"]
    return payload
