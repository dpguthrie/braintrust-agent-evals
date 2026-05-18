"""Matrix helpers for Harbor-backed Braintrust eval suites."""

from __future__ import annotations

import json
import os
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .braintrust_importer import BraintrustImportResult, Scorer, import_harbor_job_to_braintrust
from .harbor_batch import HarborBatchConfig, HarborBatchResult, run_harbor_batch, write_harbor_job_config


def env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def as_tuple(value: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return default


def enabled_items(items: list[dict[str, Any]], env_filter: str) -> list[dict[str, Any]]:
    selected = set(env_list(env_filter))
    enabled = [item for item in items if item.get("enabled", True)]
    if selected:
        enabled = [item for item in enabled if item.get("name") in selected]
    return enabled


def slug(value: str) -> str:
    normalized = value.lower().replace("/", "-").replace("_", "-")
    return "".join(char if char.isalnum() or char == "-" else "-" for char in normalized).strip("-")


def load_toml_matrix(path: str | os.PathLike[str]) -> dict[str, Any]:
    matrix_path = Path(path).resolve()
    if not matrix_path.exists():
        raise FileNotFoundError(f"Matrix config not found: {matrix_path}")
    with matrix_path.open("rb") as handle:
        return tomllib.load(handle)


def default_model_for_agent(agent: str) -> str:
    agent_name = agent.lower()
    if agent_name == "claude-code":
        return "anthropic/claude-sonnet-4-6"
    if agent_name in {"gemini", "gemini-cli"}:
        return "google/gemini-2.5-pro"
    return "openai/gpt-5.4"


def default_agent_for_model(model: str) -> str:
    model_name = model.lower()
    if model_name.startswith(("anthropic/", "claude")):
        return "claude-code"
    if model_name.startswith(("google/", "gemini/")):
        return "gemini"
    return "codex"


def matrix_targets(matrix: Mapping[str, Any], *, env_prefix: str = "HARBOR") -> list[dict[str, Any]]:
    env_agent = os.getenv(f"{env_prefix}_AGENT")
    env_model = os.getenv(f"{env_prefix}_MODEL")
    env_models = env_list(f"{env_prefix}_MODELS")
    if env_agent or env_model or env_models:
        agent = env_agent or default_agent_for_model(env_model or (env_models[0] if env_models else "openai/gpt-5.4"))
        models = env_models or ((env_model,) if env_model else (default_model_for_agent(agent),))
        return [
            {
                "name": os.getenv(f"{env_prefix}_TARGET_NAME", "env-target"),
                "agent": agent,
                "agent_import_path": os.getenv(f"{env_prefix}_AGENT_IMPORT_PATH"),
                "models": list(models),
                "enabled": True,
            }
        ]
    return enabled_items(list(matrix.get("targets", [])), f"{env_prefix}_TARGETS")


def matrix_conditions(matrix: Mapping[str, Any], *, env_prefix: str = "HARBOR") -> list[dict[str, Any]]:
    if os.getenv(f"{env_prefix}_CONDITION"):
        return [{"name": os.getenv(f"{env_prefix}_CONDITION"), "enabled": True, "extra_args": []}]
    return enabled_items(list(matrix.get("conditions") or [{"name": "default", "enabled": True}]), f"{env_prefix}_CONDITIONS")


def matrix_named_items(
    matrix: Mapping[str, Any],
    key: str,
    *,
    default_name: str,
    env_name: str,
) -> list[dict[str, Any]]:
    return enabled_items(list(matrix.get(key) or [{"name": default_name, "enabled": True}]), env_name)


def agent_env_templates(agent: str, model: str, *, env_keys: tuple[str, ...] | None = None) -> dict[str, str]:
    keys = list(env_keys if env_keys is not None else env_list("HARBOR_AGENT_ENV_KEYS"))
    agent_name = agent.lower()
    model_name = model.lower()
    if not keys:
        if agent_name == "claude-code" or model_name.startswith("anthropic/"):
            if os.getenv("ANTHROPIC_AUTH_TOKEN"):
                keys.append("ANTHROPIC_AUTH_TOKEN")
            elif os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
                keys.append("CLAUDE_CODE_OAUTH_TOKEN")
            else:
                keys.append("ANTHROPIC_API_KEY")
            if os.getenv("ANTHROPIC_BASE_URL"):
                keys.append("ANTHROPIC_BASE_URL")
        elif agent_name == "codex" or model_name.startswith("openai/"):
            if os.getenv("OPENAI_API_KEY") or not (os.getenv("CODEX_AUTH_JSON_PATH") or os.getenv("CODEX_FORCE_AUTH_JSON")):
                keys.append("OPENAI_API_KEY")
            if os.getenv("OPENAI_BASE_URL"):
                keys.append("OPENAI_BASE_URL")
            if os.getenv("CODEX_AUTH_JSON_PATH"):
                keys.append("CODEX_AUTH_JSON_PATH")
            if os.getenv("CODEX_FORCE_AUTH_JSON"):
                keys.append("CODEX_FORCE_AUTH_JSON")
        if model_name.startswith(("google/", "gemini/")):
            keys.append("GEMINI_API_KEY" if os.getenv("GEMINI_API_KEY") else "GOOGLE_API_KEY")
    return {key: f"${{{key}}}" for key in keys if key}


def missing_agent_env(agent: str, model: str) -> list[str]:
    agent_name = agent.lower()
    model_name = model.lower()
    alternatives: list[tuple[str, ...]] = []
    if agent_name == "claude-code" or model_name.startswith("anthropic/"):
        alternatives.append(("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"))
    elif agent_name == "codex" or model_name.startswith("openai/"):
        if not (os.getenv("CODEX_AUTH_JSON_PATH") or os.getenv("CODEX_FORCE_AUTH_JSON")):
            alternatives.append(("OPENAI_API_KEY",))
    elif agent_name == "gemini" or model_name.startswith(("google/", "gemini/")):
        alternatives.append(("GOOGLE_API_KEY", "GEMINI_API_KEY"))
    return [" or ".join(keys) for keys in alternatives if not any(os.getenv(key) for key in keys)]


@dataclass(frozen=True)
class HarborAgentMatrix:
    agents: list[dict[str, Any]]
    missing_env: list[str]

    def require_credentials(self) -> "HarborAgentMatrix":
        if self.missing_env:
            raise RuntimeError("Missing provider credential environment variable(s): " + "; ".join(self.missing_env))
        return self


def build_harbor_agents(targets: list[dict[str, Any]]) -> HarborAgentMatrix:
    agents: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[tuple[str, str | None, str]] = set()
    for target in targets:
        target_name = str(target.get("name") or target.get("agent") or "target")
        agent = str(target.get("agent", "codex"))
        agent_import_path = target.get("agent_import_path")
        for model in as_tuple(target.get("models"), (default_model_for_agent(agent),)):
            key = (agent, str(agent_import_path) if agent_import_path else None, model)
            if key in seen:
                continue
            seen.add(key)
            missing.extend(f"{target_name} ({model}): {item}" for item in missing_agent_env(agent, model))
            agents.append(
                {
                    "name": agent,
                    "import_path": str(agent_import_path) if agent_import_path else None,
                    "model_name": model,
                    "env": agent_env_templates(agent, model),
                    "kwargs": target.get("kwargs", {}),
                }
            )
    return HarborAgentMatrix(agents=agents, missing_env=missing)


def write_matrix_harbor_config(
    *,
    path: str | os.PathLike[str],
    job_name: str,
    tasks_dir: str | os.PathLike[str],
    agents: list[dict[str, Any]],
    defaults: Mapping[str, Any] | None = None,
) -> Path:
    defaults = defaults or {}
    config = {
        "job_name": job_name,
        "jobs_dir": os.getenv("HARBOR_JOBS_DIR", str(defaults.get("jobs_dir", "jobs"))),
        "n_concurrent_trials": int(os.getenv("HARBOR_MAX_CONCURRENCY", str(defaults.get("max_concurrency", 4)))),
        "n_attempts": int(os.getenv("HARBOR_N_ATTEMPTS", "1")),
        "quiet": os.getenv("HARBOR_QUIET", "0") == "1",
        "retry": {"max_retries": int(os.getenv("HARBOR_MAX_RETRIES", "0"))},
        "environment": {"type": os.getenv("HARBOR_ENV", "docker")},
        "datasets": [{"path": str(tasks_dir)}],
        "agents": agents,
    }
    return write_harbor_job_config(path, config)


@dataclass(frozen=True)
class RunAndImportConfig:
    job_name: str
    config_path: str
    jobs_dir: str = "jobs"
    harbor_bin: str = "harbor"
    timeout_sec: int = 7200
    braintrust_project: str | None = None
    experiment_name: str | None = None
    upload: bool = False
    extra_args: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None
    suite_artifacts: Any = None
    scorers: tuple[Scorer, ...] = ()


@dataclass(frozen=True)
class RunAndImportResult:
    harbor: HarborBatchResult
    braintrust: BraintrustImportResult | None = None

    def as_dict(self) -> dict[str, Any]:
        braintrust: dict[str, Any] | None = None
        if self.braintrust is not None:
            braintrust = {
                "project": self.braintrust.project,
                "experiment_name": self.braintrust.experiment_name,
                "experiment_id": self.braintrust.experiment_id,
                "uploaded": self.braintrust.uploaded,
                "row_count": self.braintrust.row_count,
                "preview_path": self.braintrust.preview_path,
            }
        return {
            "harbor": self.harbor.as_dict(),
            "braintrust": braintrust,
        }


def run_and_import(config: RunAndImportConfig) -> RunAndImportResult:
    batch_result = run_harbor_batch(
        HarborBatchConfig(
            job_name=config.job_name,
            config_path=config.config_path,
            jobs_dir=config.jobs_dir,
            harbor_bin=config.harbor_bin,
            timeout_sec=config.timeout_sec,
            extra_args=config.extra_args,
        )
    )
    if batch_result.job_dir is None or not config.braintrust_project:
        return RunAndImportResult(harbor=batch_result)

    import_result = import_harbor_job_to_braintrust(
        job_dir=batch_result.job_dir,
        project=config.braintrust_project,
        experiment_name=config.experiment_name or config.job_name,
        scorers=config.scorers,
        upload=config.upload,
        metadata={**(config.metadata or {}), "harbor_job": batch_result.as_dict()},
        suite_artifacts=config.suite_artifacts,
    )
    return RunAndImportResult(harbor=batch_result, braintrust=import_result)


def env_extra_args(name: str = "HARBOR_EXTRA_ARGS") -> tuple[str, ...]:
    return tuple(shlex.split(os.getenv(name, "")))


def generated_run_id(env_name: str = "HARBOR_RUN_ID") -> str:
    return os.getenv(env_name, uuid4().hex[:8])


def read_job_name(config_path: str | os.PathLike[str]) -> str:
    value = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return str(value["job_name"])
