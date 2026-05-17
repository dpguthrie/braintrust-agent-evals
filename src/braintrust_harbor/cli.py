"""Command line interface for Harbor-to-Braintrust agent evals."""

from __future__ import annotations

import argparse
import importlib
import importlib.resources as resources
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .artifacts import SuiteArtifactConfig, load_optional_json
from .braintrust_importer import import_harbor_job_to_braintrust
from .harbor_batch import HarborBatchConfig, run_harbor_batch


def _json_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    value = load_optional_json(Path(path))
    if value is None:
        raise FileNotFoundError(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _scorer_from_ref(ref: str) -> Any:
    module_name, sep, attr_path = ref.partition(":")
    if not sep or not module_name or not attr_path:
        raise ValueError(f"Scorer reference must look like 'module:object', got {ref!r}")
    module = importlib.import_module(module_name)
    value: Any = module
    for part in attr_path.split("."):
        value = getattr(value, part)
    return value


def _scorers(refs: list[str]) -> list[Any]:
    return [_scorer_from_ref(ref) for ref in refs]


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _add_import_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, help="Braintrust project name.")
    parser.add_argument("--experiment-name", help="Braintrust experiment name. Defaults to the Harbor job directory name.")
    parser.add_argument("--upload", action="store_true", help="Upload rows to Braintrust. Without this, write a preview JSON file.")
    parser.add_argument("--preview-path", help="Where to write preview JSON when --upload is not set.")
    parser.add_argument("--suite-artifacts", help="JSON file describing suite-owned artifacts to load from Harbor trials.")
    parser.add_argument("--metadata", help="JSON object file to attach as experiment metadata.")
    parser.add_argument(
        "--scorer",
        action="append",
        default=[],
        help="Braintrust-compatible scorer reference, e.g. 'my_suite.scorers:quality_score'. Repeatable.",
    )


def run_cmd(args: argparse.Namespace) -> int:
    result = run_harbor_batch(
        HarborBatchConfig(
            job_name=args.job_name,
            config_path=args.config,
            jobs_dir=args.jobs_dir,
            harbor_bin=args.harbor_bin,
            timeout_sec=args.timeout_sec,
            extra_args=tuple(args.harbor_arg or ()),
        )
    )
    if result.job_dir is None or result.returncode not in (0, None):
        _print_json({"harbor": result.as_dict()})
        return int(result.returncode or 1)

    if not args.project:
        _print_json({"harbor": result.as_dict()})
        return int(result.returncode or 0)

    import_result = import_harbor_job_to_braintrust(
        job_dir=result.job_dir,
        project=args.project,
        experiment_name=args.experiment_name or result.job_name,
        scorers=_scorers(args.scorer),
        upload=args.upload,
        preview_path=args.preview_path,
        metadata={**_json_file(args.metadata), "harbor_job": result.as_dict()},
        suite_artifacts=SuiteArtifactConfig.from_dict(_json_file(args.suite_artifacts)),
    )
    _print_json(
        {
            "harbor": result.as_dict(),
            "braintrust": {
                "project": import_result.project,
                "experiment_name": import_result.experiment_name,
                "experiment_id": import_result.experiment_id,
                "uploaded": import_result.uploaded,
                "row_count": import_result.row_count,
                "preview_path": import_result.preview_path,
            },
        }
    )
    return int(result.returncode or 0)


def import_cmd(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    result = import_harbor_job_to_braintrust(
        job_dir=str(job_dir),
        project=args.project,
        experiment_name=args.experiment_name or job_dir.name,
        scorers=_scorers(args.scorer),
        upload=args.upload,
        preview_path=args.preview_path,
        metadata=_json_file(args.metadata),
        suite_artifacts=SuiteArtifactConfig.from_dict(_json_file(args.suite_artifacts)),
    )
    _print_json(
        {
            "project": result.project,
            "experiment_name": result.experiment_name,
            "experiment_id": result.experiment_id,
            "uploaded": result.uploaded,
            "row_count": result.row_count,
            "preview_path": result.preview_path,
        }
    )
    return 0


def init_cmd(args: argparse.Namespace) -> int:
    destination = Path(args.path).resolve()
    if destination.exists() and any(destination.iterdir()) and not args.force:
        raise FileExistsError(f"{destination} already exists and is not empty. Use --force to overwrite template files.")
    template_root = resources.files("braintrust_harbor.templates").joinpath(args.template)
    if not template_root.exists():
        raise FileNotFoundError(f"Template not found: {args.template}")
    destination.mkdir(parents=True, exist_ok=True)
    with resources.as_file(template_root) as template_path:
        for child in template_path.iterdir():
            target = destination / child.name
            if target.exists() and args.force:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=args.force)
            else:
                shutil.copy2(child, target)
    _print_json({"created": str(destination), "template": args.template})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt-harbor",
        description="Run Harbor coding-agent jobs and import the results into Braintrust.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one Harbor job config, optionally importing it to Braintrust.")
    run_parser.add_argument("config", help="Harbor job config JSON path.")
    run_parser.add_argument("--job-name", help="Harbor job name. Defaults to Harbor/package generated name.")
    run_parser.add_argument("--jobs-dir", default="jobs", help="Harbor jobs directory.")
    run_parser.add_argument("--harbor-bin", default="harbor", help="Harbor executable path/name.")
    run_parser.add_argument("--timeout-sec", type=int, default=7200, help="Timeout for the Harbor process.")
    run_parser.add_argument("--harbor-arg", action="append", help="Extra argument passed through to `harbor run`. Repeatable.")
    _add_import_args(run_parser)
    run_parser.set_defaults(func=run_cmd)

    import_parser = subparsers.add_parser("import", help="Import an existing Harbor job directory into Braintrust.")
    import_parser.add_argument("job_dir", help="Harbor job directory.")
    _add_import_args(import_parser)
    import_parser.set_defaults(func=import_cmd)

    init_parser = subparsers.add_parser("init", help="Copy an example suite template into a new directory.")
    init_parser.add_argument("path", help="Destination directory.")
    init_parser.add_argument("--template", default="minimal-cli-tool", help="Template name from examples/.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing template files.")
    init_parser.set_defaults(func=init_cmd)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"bt-harbor: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
