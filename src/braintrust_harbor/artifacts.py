"""Artifact loading for Harbor trial directories.

Harbor writes one job directory per `harbor run` invocation and a trial
directory below it. This module keeps parsing deliberately tolerant because the
exact agent log files vary by Harbor agent implementation.
"""

from __future__ import annotations

import json
import os
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import extract_usage_metrics


@dataclass(frozen=True)
class ArtifactSpec:
    """One suite-owned artifact to load from a Harbor trial."""

    key: str
    paths: tuple[str, ...]
    kind: str = "json"
    limit: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArtifactSpec":
        paths = value.get("paths", ())
        if isinstance(paths, str):
            normalized_paths = (paths,)
        elif isinstance(paths, list | tuple):
            normalized_paths = tuple(str(item) for item in paths)
        else:
            normalized_paths = ()
        limit = value.get("limit")
        return cls(
            key=str(value["key"]),
            paths=normalized_paths,
            kind=str(value.get("kind") or "json"),
            limit=int(limit) if isinstance(limit, int | float) else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "paths": list(self.paths),
            "kind": self.kind,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class SuiteArtifactConfig:
    """Suite-owned artifact mapping layered on top of Harbor's layout.

    Harbor itself provides stable trial files such as ``result.json``,
    ``config.json``, ``verifier/reward.json``, ``agent/trajectory.json``, and
    the collected ``artifacts/`` directory. Product-specific outputs inside
    ``artifacts/`` are not a Harbor contract, so callers configure them here.
    """

    artifacts: tuple[ArtifactSpec, ...] = ()
    command_log_key: str | None = None
    command_span_prefix: str = "command"
    command_tool_name: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "SuiteArtifactConfig":
        if not isinstance(value, dict):
            return cls()

        artifacts: list[ArtifactSpec] = []
        for item in value.get("artifacts") or ():
            if isinstance(item, ArtifactSpec):
                artifacts.append(item)
            elif isinstance(item, dict):
                artifacts.append(ArtifactSpec.from_dict(item))

        return cls(
            artifacts=tuple(artifacts),
            command_log_key=(
                str(value["command_log_key"])
                if value.get("command_log_key") is not None
                else None
            ),
            command_span_prefix=str(value.get("command_span_prefix") or "command"),
            command_tool_name=(
                str(value["command_tool_name"])
                if value.get("command_tool_name") is not None
                else None
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "command_log_key": self.command_log_key,
            "command_span_prefix": self.command_span_prefix,
            "command_tool_name": self.command_tool_name,
        }


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: Path, limit: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit is not None and len(text) > limit:
        return text[-limit:]
    return text


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "parse_error": str(exc),
                        "line_number": line_number,
                        "line": stripped,
                    }
                )
                continue
            if isinstance(value, dict):
                rows.append(value)
            else:
                rows.append({"value": value, "line_number": line_number})
    return rows


def latest_child_dir(parent: Path, since: float | None = None) -> Path | None:
    if not parent.exists():
        return None
    dirs = [path for path in parent.iterdir() if path.is_dir()]
    if since is not None:
        dirs = [path for path in dirs if path.stat().st_mtime >= since]
    if not dirs:
        return None
    return max(dirs, key=lambda path: path.stat().st_mtime)


def find_trial_dirs(job_dir: Path) -> list[Path]:
    if not job_dir.exists():
        return []
    candidates: list[Path] = []
    for result_path in job_dir.rglob("result.json"):
        parent = result_path.parent
        if parent == job_dir:
            continue
        if (
            (parent / "config.json").exists()
            and (
                (parent / "verifier").exists()
                or (parent / "artifacts").exists()
                or (parent / "agent").exists()
                or (parent / "steps").exists()
                or (parent / "trial.log").exists()
            )
        ):
            candidates.append(parent)
    if candidates:
        return sorted(set(candidates), key=lambda path: str(path))

    for verifier_dir in job_dir.rglob("verifier"):
        if verifier_dir.is_dir():
            candidates.append(verifier_dir.parent)
    return sorted(set(candidates), key=lambda path: str(path))


def find_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _contract_path_candidates(trial_path: Path, configured_paths: tuple[str, ...]) -> list[Path]:
    artifacts_dir = trial_path / "artifacts"
    verifier_dir = trial_path / "verifier"
    agent_dir = trial_path / "agent"
    candidates: list[Path] = []
    for configured in configured_paths:
        text = configured.strip()
        if not text:
            continue
        if text.startswith("/logs/artifacts/"):
            candidates.append(artifacts_dir / text.removeprefix("/logs/artifacts/"))
        elif text.startswith("/logs/verifier/"):
            candidates.append(verifier_dir / text.removeprefix("/logs/verifier/"))
        elif text.startswith("/logs/agent/"):
            candidates.append(agent_dir / text.removeprefix("/logs/agent/"))
        elif "/" in text:
            candidates.append(trial_path / text)
        else:
            candidates.extend(
                [
                    artifacts_dir / text,
                    trial_path / text,
                    verifier_dir / text,
                ]
            )
    return candidates


def parse_reward(trial_dir: Path) -> dict[str, float]:
    reward_json = trial_dir / "verifier" / "reward.json"
    reward_txt = trial_dir / "verifier" / "reward.txt"
    if reward_json.exists():
        value = read_json(reward_json)
        if isinstance(value, dict):
            return {
                str(key): float(score)
                for key, score in value.items()
                if isinstance(score, int | float)
            }
        if isinstance(value, int | float):
            return {"reward": float(value)}
    if reward_txt.exists():
        text = reward_txt.read_text(encoding="utf-8").strip()
        try:
            return {"reward": float(text)}
        except ValueError:
            return {}
    return {}


def load_optional_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return read_json(path)
    except json.JSONDecodeError as exc:
        return {"parse_error": str(exc), "path": str(path)}


def _load_artifact_value(path: Path, spec: ArtifactSpec) -> Any:
    kind = spec.kind.lower()
    if kind == "json":
        return load_optional_json(path)
    if kind == "jsonl":
        return read_jsonl(path)
    if kind == "text":
        return read_text(path, limit=spec.limit)
    if kind == "path":
        return str(path)
    return read_text(path, limit=spec.limit)


def _duration_seconds(started_at: Any, finished_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        start = dt.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = dt.datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((finish - start).total_seconds(), 3)


def _load_runtime_dirs(
    runtime_path: Path,
    contract: SuiteArtifactConfig,
) -> dict[str, Any]:
    artifacts_dir = runtime_path / "artifacts"
    verifier_dir = runtime_path / "verifier"
    agent_dir = runtime_path / "agent"
    output: dict[str, Any] = {
        "runtime_dir": str(runtime_path),
        "reward": parse_reward(runtime_path),
        "reward_details": load_optional_json(verifier_dir / "reward-details.json"),
        "artifact_manifest": load_optional_json(artifacts_dir / "manifest.json"),
        "trajectory": None,
        "artifacts": {},
    }
    trajectory_path = find_first_existing(
        [
            agent_dir / "trajectory.json",
            artifacts_dir / "trajectory.json",
            agent_dir / "atif.json",
            artifacts_dir / "atif.json",
        ]
    )
    output["trajectory"] = load_optional_json(trajectory_path)
    for spec in contract.artifacts:
        artifact_path = find_first_existing(_contract_path_candidates(runtime_path, spec.paths))
        if artifact_path is not None:
            output[spec.key] = _load_artifact_value(artifact_path, spec)
    if artifacts_dir.exists():
        for path in artifacts_dir.glob("*"):
            if path.is_file():
                output["artifacts"][path.name] = str(path)
    return output


def _load_task_sidecar(task_path: Path | None) -> dict[str, Any]:
    if task_path is None:
        return {}

    sidecar = load_optional_json(task_path / ".agent-tooling-eval.json")
    if isinstance(sidecar, dict):
        return sidecar
    return {}


def load_harbor_trial_output(
    *,
    job_dir: str | os.PathLike[str] | None,
    trial_dir: str | os.PathLike[str] | None = None,
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load Harbor trial output plus optional suite-owned artifacts."""

    contract = (
        suite_artifacts
        if isinstance(suite_artifacts, SuiteArtifactConfig)
        else SuiteArtifactConfig.from_dict(suite_artifacts)
    )

    job_path = Path(job_dir).resolve() if job_dir else None
    trial_path: Path | None
    if trial_dir:
        trial_path = Path(trial_dir).resolve()
    elif job_path:
        trial_dirs = find_trial_dirs(job_path)
        trial_path = trial_dirs[0] if trial_dirs else None
    else:
        trial_path = None

    output: dict[str, Any] = {
        "job_dir": str(job_path) if job_path else None,
        "trial_dir": str(trial_path) if trial_path else None,
        "suite_artifacts": contract.as_dict(),
        "reward": {},
        "reward_details": None,
        "artifact_manifest": None,
        "trajectory": None,
        "usage_metrics": {},
        "harbor_result": None,
        "exception_text": "",
        "trial_log": "",
        "artifacts": {},
        "steps": {},
    }
    if trial_path is None:
        return output

    output["harbor_result"] = load_optional_json(trial_path / "result.json")
    if (trial_path / "exception.txt").exists():
        output["exception_text"] = read_text(trial_path / "exception.txt", limit=20000)
    if (trial_path / "trial.log").exists():
        output["trial_log"] = read_text(trial_path / "trial.log", limit=20000)

    output.update(_load_runtime_dirs(trial_path, contract))
    steps_dir = trial_path / "steps"
    if steps_dir.exists():
        for step_path in sorted(path for path in steps_dir.iterdir() if path.is_dir()):
            output["steps"][step_path.name] = _load_runtime_dirs(step_path, contract)

    output["usage_metrics"] = extract_usage_metrics(output)

    return output


def load_harbor_job_outputs(
    job_dir: str | os.PathLike[str],
    *,
    metadata_by_task: dict[str, dict[str, Any]] | None = None,
    suite_artifacts: SuiteArtifactConfig | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Load every trial output below one Harbor job directory."""

    contract = (
        suite_artifacts
        if isinstance(suite_artifacts, SuiteArtifactConfig)
        else SuiteArtifactConfig.from_dict(suite_artifacts)
    )

    job_path = Path(job_dir).resolve()
    job_config = load_optional_json(job_path / "config.json")
    job_result = load_optional_json(job_path / "result.json")
    outputs: list[dict[str, Any]] = []
    for trial_path in find_trial_dirs(job_path):
        trial_config = load_optional_json(trial_path / "config.json")
        task_config = trial_config.get("task") if isinstance(trial_config, dict) else {}
        task_path = Path(str(task_config.get("path"))).resolve() if isinstance(task_config, dict) and task_config.get("path") else None
        task_name = task_path.name if task_path else trial_path.name.rsplit("__", 1)[0]
        row_metadata = (
            _load_task_sidecar(task_path)
            or (metadata_by_task or {}).get(task_name, {})
        )
        row_metadata = row_metadata if isinstance(row_metadata, dict) else {}

        output = load_harbor_trial_output(
            job_dir=job_path,
            trial_dir=trial_path,
            suite_artifacts=contract,
        )
        agent_config = trial_config.get("agent") if isinstance(trial_config, dict) else {}
        agent_config = agent_config if isinstance(agent_config, dict) else {}
        harbor_result = output.get("harbor_result") if isinstance(output.get("harbor_result"), dict) else {}
        exception_info = harbor_result.get("exception_info") if isinstance(harbor_result, dict) else None
        started_at = harbor_result.get("started_at") if isinstance(harbor_result, dict) else None
        finished_at = harbor_result.get("finished_at") if isinstance(harbor_result, dict) else None
        output.update(
            {
                "job_config": job_config,
                "job_result": job_result,
                "trial_config": trial_config,
                "task_name": task_name,
                "task_metadata": row_metadata,
                "eval_input": row_metadata.get("input"),
                "expected": row_metadata.get("expected"),
                "agent": agent_config.get("name") or row_metadata.get("agent"),
                "agent_import_path": agent_config.get("import_path"),
                "model": agent_config.get("model_name") or row_metadata.get("model"),
                "job_name": job_path.name,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_sec": _duration_seconds(started_at, finished_at),
                "returncode": 1 if exception_info else 0,
            }
        )
        outputs.append(output)
    return outputs
