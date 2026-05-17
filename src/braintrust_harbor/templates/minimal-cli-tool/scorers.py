from __future__ import annotations

from typing import Any


def summary_present(output: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    summary = output.get("summary")
    return {
        "name": "Summary present",
        "score": 1.0 if isinstance(summary, dict) and summary.get("recommendation") else 0.0,
        "metadata": {"summary_keys": sorted(summary) if isinstance(summary, dict) else []},
    }


async def inspect_before_change(trace: Any = None, **_kwargs: Any) -> dict[str, Any]:
    if trace is None:
        return {"name": "Inspect before change", "score": 0.0, "metadata": {"reason": "missing trace"}}
    spans = await trace.get_spans(["tool"])
    command_classes = [
        (getattr(span, "metadata", None) or {}).get("command_class")
        for span in spans
    ]
    inspect_index = next((idx for idx, name in enumerate(command_classes) if name == "inspect"), None)
    mutation_index = next((idx for idx, name in enumerate(command_classes) if name == "mutate"), None)
    ok = inspect_index is not None and (mutation_index is None or inspect_index < mutation_index)
    return {
        "name": "Inspect before change",
        "score": 1.0 if ok else 0.0,
        "metadata": {"command_classes": command_classes},
    }
