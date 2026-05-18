from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZE_PATH = ROOT / "src/braintrust_harbor/templates/harness-model-matrix/scripts/materialize.py"


def load_materializer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("harness_model_matrix_materialize", MATERIALIZE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {MATERIALIZE_PATH}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class HarnessModelMatrixTemplateTests(unittest.TestCase):
    def test_materializes_default_prompt_repo_task(self) -> None:
        materializer = load_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path = root / "eval-input.json"
            out_dir = root / "generated" / "current"
            write_json(
                spec_path,
                {
                    "job_name": "demo",
                    "prompt": "Inspect the repo and report back.",
                    "repo": {"url": "https://example.invalid/repo.git", "ref": "main"},
                    "task": {"name": "repo task", "expected": {"ok": True}},
                    "tooling_versions": [
                        {
                            "name": "current",
                            "install_command": "echo installing-current",
                            "agent_env": {"TOOLING_CHANNEL": "current"},
                            "metadata": {"channel": "stable"},
                        }
                    ],
                    "agents": [{"name": "codex", "model_name": "openai/test", "env": {"OPENAI_API_KEY": "${OPENAI_API_KEY}"}}],
                },
            )

            result = materializer.materialize(spec_path, out_dir, "current")

            self.assertEqual(result["tasks"], ["repo-task"])
            job = json.loads((out_dir / "harbor-job.json").read_text(encoding="utf-8"))
            self.assertEqual(job["job_name"], "demo-current")
            self.assertEqual(job["datasets"], [{"path": "tasks"}])
            self.assertEqual(job["agents"][0]["env"]["TOOLING_CHANNEL"], "current")
            instruction = (out_dir / "tasks/repo-task/instruction.md").read_text(encoding="utf-8")
            self.assertIn("Inspect the repo and report back.", instruction)
            self.assertIn("https://example.invalid/repo.git", instruction)
            sidecar = json.loads((out_dir / "tasks/repo-task/.agent-tooling-eval.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["input"]["tooling_version"], "current")
            self.assertEqual(sidecar["expected"], {"ok": True})
            self.assertEqual(sidecar["metadata"]["channel"], "stable")
            install_script = (out_dir / "tasks/repo-task/environment/install-tooling.sh").read_text(encoding="utf-8")
            self.assertIn("echo installing-current", install_script)
            self.assertTrue((out_dir / "suite-artifacts.json").exists())
            self.assertTrue((out_dir / "scorers.py").exists())

    def test_materializes_external_harbor_task_sources(self) -> None:
        materializer = load_materializer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "hello-mcp"
            source.mkdir()
            (source / "task.toml").write_text('name = "hello-mcp"\n', encoding="utf-8")
            (source / "instruction.md").write_text("Original instruction.\n", encoding="utf-8")
            spec_path = root / "eval-input.json"
            out_dir = root / "generated" / "latest"
            write_json(
                spec_path,
                {
                    "job_name": "external",
                    "prompt": "Write the summary artifact too.",
                    "tooling_versions": [{"name": "latest"}],
                    "agents": [{"name": "codex", "model_name": "openai/test"}],
                    "task_sources": [
                        {
                            "name": "hello-mcp",
                            "path": str(source),
                            "prompt_mode": "append",
                            "metadata": {"feature": "mcp"},
                        }
                    ],
                },
            )

            result = materializer.materialize(spec_path, out_dir, "latest")

            self.assertEqual(result["tasks"], ["hello-mcp"])
            copied_instruction = (out_dir / "tasks/hello-mcp/instruction.md").read_text(encoding="utf-8")
            self.assertIn("Original instruction.", copied_instruction)
            self.assertIn("Eval Prompt Overlay", copied_instruction)
            self.assertIn("Write the summary artifact too.", copied_instruction)
            sidecar = json.loads((out_dir / "tasks/hello-mcp/.agent-tooling-eval.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["metadata"]["feature"], "mcp")
            self.assertEqual(sidecar["metadata"]["tooling_version"], "latest")


if __name__ == "__main__":
    unittest.main()
