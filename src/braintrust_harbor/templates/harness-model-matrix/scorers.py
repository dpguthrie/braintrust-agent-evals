"""Example Braintrust-compatible scorers for the harness/model matrix template."""

from __future__ import annotations

from typing import Any


def _summary(output: Any) -> dict[str, Any]:
    if isinstance(output, dict) and isinstance(output.get("summary"), dict):
        return output["summary"]
    return {}


def _command_log(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, dict) and isinstance(output.get("command_log"), list):
        return [row for row in output["command_log"] if isinstance(row, dict)]
    return []


async def summary_present(output: Any = None, **_kwargs: Any) -> dict[str, Any]:
    summary = _summary(output)
    evidence = summary.get("evidence")
    ok = bool(summary.get("recommendation")) and isinstance(evidence, list) and bool(evidence)
    return {
        "name": "summary_present",
        "score": ok,
        "metadata": {
            "has_recommendation": bool(summary.get("recommendation")),
            "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        },
    }


async def used_demo_tool(output: Any = None, **_kwargs: Any) -> dict[str, Any]:
    rows = _command_log(output)
    used = [row for row in rows if row.get("tool") == "demo-tool"]
    return {
        "name": "used_demo_tool",
        "score": bool(used),
        "metadata": {
            "demo_tool_calls": len(used),
            "commands": [row.get("command") for row in rows],
        },
    }


async def no_harbor_exception(output: Any = None, **_kwargs: Any) -> dict[str, Any]:
    harbor_result = output.get("harbor_result") if isinstance(output, dict) else None
    exception_info = harbor_result.get("exception_info") if isinstance(harbor_result, dict) else None
    return {
        "name": "no_harbor_exception",
        "score": exception_info is None,
        "metadata": {
            "exception_info": exception_info,
        },
    }
