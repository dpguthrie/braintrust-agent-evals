#!/usr/bin/env python3
"""Materialize a simple Harbor harness/model matrix eval from one JSON input."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any


WORKFLOW_NAME = "harness-model-matrix"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _safe_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "-", value)
    value = value.strip(".-")
    return value or "task"


def _repo(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec.get("repo") if isinstance(spec.get("repo"), dict) else {}
    return {
        "url": str(raw.get("url") or ""),
        "ref": str(raw.get("ref") or ""),
    }


def _tooling_version(spec: dict[str, Any], name: str | None) -> dict[str, Any]:
    versions = spec.get("tooling_versions")
    if not isinstance(versions, list) or not versions:
        raise ValueError("eval input must include at least one tooling_versions entry")
    if name is None:
        value = versions[0]
        if not isinstance(value, dict):
            raise ValueError("tooling_versions entries must be objects")
        return value
    for value in versions:
        if isinstance(value, dict) and value.get("name") == name:
            return value
    available = ", ".join(str(v.get("name")) for v in versions if isinstance(v, dict))
    raise ValueError(f"Unknown tooling version {name!r}. Available: {available}")


def _merge_agent_env(agent: dict[str, Any], tooling: dict[str, Any]) -> dict[str, Any]:
    merged = dict(agent)
    env: dict[str, Any] = {}
    if isinstance(agent.get("env"), dict):
        env.update(agent["env"])
    if isinstance(tooling.get("agent_env"), dict):
        env.update(tooling["agent_env"])
    if env:
        merged["env"] = env
    return merged


def _harbor_job(spec: dict[str, Any], tooling: dict[str, Any]) -> dict[str, Any]:
    harbor = spec.get("harbor") if isinstance(spec.get("harbor"), dict) else {}
    job: dict[str, Any] = {
        "job_name": f"{spec.get('job_name', 'harness-model')}-{tooling.get('name', 'tooling')}",
        "jobs_dir": harbor.get("jobs_dir", "jobs"),
        "n_attempts": harbor.get("n_attempts", 1),
        "n_concurrent_trials": harbor.get("n_concurrent_trials", 2),
        "environment": harbor.get("environment", {"type": "docker"}),
        "datasets": [{"path": "tasks"}],
        "agents": [],
    }
    agents = spec.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("eval input must include at least one agent")
    job["agents"] = [_merge_agent_env(agent, tooling) for agent in agents if isinstance(agent, dict)]
    if not job["agents"]:
        raise ValueError("eval input did not include any valid agent objects")
    return job


def _metadata(
    spec: dict[str, Any],
    tooling: dict[str, Any],
    *,
    task_name: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = _repo(spec)
    task = spec.get("task") if isinstance(spec.get("task"), dict) else {}
    metadata: dict[str, Any] = {
        "workflow": WORKFLOW_NAME,
        "scenario": task_name,
        "tooling_version": tooling.get("name"),
        "tooling_install_command_present": bool(tooling.get("install_command")),
        "repo_url": repo["url"],
        "repo_ref": repo["ref"],
    }
    if isinstance(task.get("metadata"), dict):
        metadata.update(task["metadata"])
    if isinstance(tooling.get("metadata"), dict):
        metadata.update(tooling["metadata"])
    if extra:
        metadata.update(extra)
    return metadata


def _sidecar(
    spec: dict[str, Any],
    tooling: dict[str, Any],
    *,
    task_name: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = spec.get("task") if isinstance(spec.get("task"), dict) else {}
    expected = task.get("expected") if isinstance(task.get("expected"), dict) else {}
    return {
        "input": {
            "prompt": str(spec.get("prompt") or ""),
            "repo": _repo(spec),
            "tooling_version": tooling.get("name"),
        },
        "expected": expected,
        "metadata": _metadata(spec, tooling, task_name=task_name, extra=extra_metadata),
    }


def _instruction(prompt: str, tooling_name: str, repo: dict[str, str]) -> str:
    repo_note = "A toy repository is available at `/app/repo`."
    if repo["url"]:
        ref = f" at ref `{repo['ref']}`" if repo["ref"] else ""
        repo_note = f"The requested repository has been cloned to `/app/repo` from `{repo['url']}`{ref}."
    return f"""# Harness/Model Matrix Scenario

{prompt}

Context:

- Tooling version under test: `{tooling_name}`
- {repo_note}
- The `demo-tool` CLI is available on `PATH`.

Write these artifacts:

- `/logs/artifacts/summary.json`
- `/logs/artifacts/narrative.md`

The summary JSON must include:

```json
{{
  "recommendation": "string",
  "evidence": ["string"]
}}
```
"""


def _install_script(tooling: dict[str, Any]) -> str:
    name = str(tooling.get("name") or "tooling")
    command = str(tooling.get("install_command") or "").strip()
    if command:
        install_block = command + "\n"
    else:
        install_block = "echo 'No tooling install command configured; using bundled demo-tool.'\n"
    return f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p /opt/harness-model-matrix
printf '%s\\n' {json.dumps(name)} > /opt/harness-model-matrix/tooling-version.txt
{install_block}"""


def _bootstrap_repo_script(repo: dict[str, str]) -> str:
    repo_url = repo["url"]
    repo_ref = repo["ref"]
    return f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app
REPO_URL={json.dumps(repo_url)}
REPO_REF={json.dumps(repo_ref)}
if [ -n "$REPO_URL" ]; then
  git clone --depth 1 "$REPO_URL" /app/repo
  if [ -n "$REPO_REF" ]; then
    cd /app/repo
    git fetch --depth 1 origin "$REPO_REF" || true
    git checkout "$REPO_REF"
  fi
else
  mkdir -p /app/repo
  cat > /app/repo/README.md <<'EOF'
# Demo Repository

This tiny repo exists so agents have a workspace to inspect when no external
repository is configured.
EOF
fi
"""


def _copy_helper_files(template_root: Path, out_dir: Path) -> None:
    for name in ("suite-artifacts.json", "scorers.py"):
        source = template_root / name
        if source.exists():
            shutil.copy2(source, out_dir / name)


def _materialize_default_task(
    spec: dict[str, Any],
    tooling: dict[str, Any],
    *,
    template_root: Path,
    out_dir: Path,
) -> list[str]:
    task_spec = spec.get("task") if isinstance(spec.get("task"), dict) else {}
    task_name = _safe_name(str(task_spec.get("name") or "prompted-tooling-task"))
    task_dir = out_dir / "tasks" / task_name
    shutil.copytree(template_root / "task-template", task_dir, dirs_exist_ok=True)
    (task_dir / "instruction.md").write_text(
        _instruction(str(spec.get("prompt") or ""), str(tooling.get("name") or "tooling"), _repo(spec)),
        encoding="utf-8",
    )
    _write_json(task_dir / ".agent-tooling-eval.json", _sidecar(spec, tooling, task_name=task_name))
    _write_executable(task_dir / "environment" / "install-tooling.sh", _install_script(tooling))
    _write_executable(task_dir / "environment" / "bootstrap-repo.sh", _bootstrap_repo_script(_repo(spec)))
    return [task_name]


def _resolve_source_path(spec_path: Path, raw_path: str) -> Path:
    source = Path(os.path.expanduser(raw_path))
    if not source.is_absolute():
        source = (spec_path.parent / source).resolve()
    return source


def _materialize_task_sources(
    spec: dict[str, Any],
    tooling: dict[str, Any],
    *,
    spec_path: Path,
    out_dir: Path,
) -> list[str]:
    task_names: list[str] = []
    prompt = str(spec.get("prompt") or "")
    sources = spec.get("task_sources")
    if not isinstance(sources, list):
        return task_names

    for raw_source in sources:
        if not isinstance(raw_source, dict):
            raise ValueError("task_sources entries must be objects")
        source_path = _resolve_source_path(spec_path, str(raw_source.get("path") or ""))
        if not source_path.exists():
            raise FileNotFoundError(f"Task source not found: {source_path}")
        task_name = _safe_name(str(raw_source.get("name") or source_path.name))
        task_dir = out_dir / "tasks" / task_name
        shutil.copytree(source_path, task_dir, dirs_exist_ok=True)

        instruction_path = task_dir / "instruction.md"
        mode = str(raw_source.get("prompt_mode") or "append")
        if prompt:
            original = instruction_path.read_text(encoding="utf-8") if instruction_path.exists() else ""
            overlay = f"\n\n## Eval Prompt Overlay\n\n{prompt}\n"
            if mode == "replace":
                instruction_path.write_text(prompt + "\n", encoding="utf-8")
            elif mode == "append":
                instruction_path.write_text(original.rstrip() + overlay, encoding="utf-8")
            else:
                raise ValueError(f"Unsupported prompt_mode for {task_name}: {mode}")

        metadata = {"source_path": str(source_path)}
        if isinstance(raw_source.get("metadata"), dict):
            metadata.update(raw_source["metadata"])
        _write_json(
            task_dir / ".agent-tooling-eval.json",
            _sidecar(spec, tooling, task_name=task_name, extra_metadata=metadata),
        )
        task_names.append(task_name)
    return task_names


def materialize(spec_path: Path, out_dir: Path, tooling_version: str | None = None) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    out_dir = out_dir.resolve()
    spec = _json(spec_path)
    tooling = _tooling_version(spec, tooling_version)
    template_root = Path(__file__).resolve().parents[1]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks").mkdir(parents=True, exist_ok=True)

    task_sources = spec.get("task_sources")
    if isinstance(task_sources, list) and task_sources:
        task_names = _materialize_task_sources(spec, tooling, spec_path=spec_path, out_dir=out_dir)
    else:
        task_names = _materialize_default_task(spec, tooling, template_root=template_root, out_dir=out_dir)

    harbor_job = _harbor_job(spec, tooling)
    _write_json(out_dir / "harbor-job.json", harbor_job)
    _copy_helper_files(template_root, out_dir)
    run_metadata = {
        "workflow": WORKFLOW_NAME,
        "project": spec.get("project"),
        "prompt": spec.get("prompt"),
        "repo": _repo(spec),
        "tooling_version": tooling.get("name"),
        "tooling_metadata": tooling.get("metadata") if isinstance(tooling.get("metadata"), dict) else {},
        "tasks": task_names,
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }
    _write_json(out_dir / "metadata.json", run_metadata)
    return {
        "out_dir": str(out_dir),
        "harbor_job": str(out_dir / "harbor-job.json"),
        "metadata": str(out_dir / "metadata.json"),
        "tasks": task_names,
        "tooling_version": tooling.get("name"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="eval-input.json", help="Eval input JSON file.")
    parser.add_argument("--tooling-version", help="Name from tooling_versions. Defaults to the first entry.")
    parser.add_argument("--out", default=None, help="Output directory. Defaults to generated/<tooling-version>.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    spec_path = Path(args.input)
    spec = _json(spec_path)
    tooling = _tooling_version(spec, args.tooling_version)
    out_dir = Path(args.out or Path("generated") / str(tooling.get("name") or "tooling"))
    result = materialize(spec_path, out_dir, str(tooling.get("name")))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
