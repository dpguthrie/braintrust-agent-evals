"""Harbor-first batch execution helpers.

The abstraction here is intentionally thin: Harbor owns agent execution,
sandboxing, and trial parallelism. This module only writes a Harbor job config,
runs one `harbor run --config ...` command, and returns the job directory.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .artifacts import latest_child_dir


@dataclass(frozen=True)
class HarborBatchConfig:
    job_name: str | None
    config_path: str
    jobs_dir: str = "jobs"
    harbor_bin: str = "harbor"
    timeout_sec: int = 7200
    extra_args: tuple[str, ...] = ()


@dataclass
class HarborBatchResult:
    job_name: str
    job_dir: str | None
    config_path: str
    command: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_sec: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_name": self.job_name,
            "job_dir": self.job_dir,
            "config_path": self.config_path,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            **self.extra,
        }


def write_harbor_job_config(path: str | os.PathLike[str], config: dict[str, Any]) -> Path:
    config_path = Path(path).resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config_path


def _subprocess_env(cwd: Path) -> dict[str, str]:
    env = os.environ.copy()
    repo_path = str(cwd)
    existing = env.get("PYTHONPATH")
    parts = existing.split(os.pathsep) if existing else []
    if repo_path not in parts:
        env["PYTHONPATH"] = os.pathsep.join([repo_path, *parts]) if parts else repo_path
    return env


def run_harbor_batch(config: HarborBatchConfig) -> HarborBatchResult:
    job_name = config.job_name or f"agent-tooling-{uuid4().hex[:12]}"
    command = [
        config.harbor_bin,
        "run",
        "--config",
        config.config_path,
        "--job-name",
        job_name,
        *config.extra_args,
    ]
    cwd = Path.cwd()
    jobs_dir = (cwd / config.jobs_dir).resolve()
    expected_job_dir = jobs_dir / job_name
    start = time.time()
    result = HarborBatchResult(
        job_name=job_name,
        job_dir=None,
        config_path=config.config_path,
        command=command,
        returncode=None,
        started_at=dt.datetime.fromtimestamp(start, tz=dt.UTC).isoformat(),
    )

    if shutil.which(config.harbor_bin) is None:
        result.returncode = 127
        result.error = f"Harbor binary not found: {config.harbor_bin}"
    else:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_subprocess_env(cwd),
                timeout=config.timeout_sec,
                check=False,
            )
            result.returncode = completed.returncode
            result.stdout = completed.stdout[-20000:]
            result.stderr = completed.stderr[-20000:]
        except subprocess.TimeoutExpired as exc:
            result.returncode = 124
            result.stdout = (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else ""
            result.stderr = (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else ""
            result.error = f"Harbor timed out after {config.timeout_sec}s"

    job_dir = expected_job_dir if expected_job_dir.exists() else latest_child_dir(jobs_dir, since=start - 1.0)
    if job_dir is not None:
        result.job_dir = str(job_dir)
    finish = time.time()
    result.finished_at = dt.datetime.fromtimestamp(finish, tz=dt.UTC).isoformat()
    result.duration_sec = round(finish - start, 3)
    return result
