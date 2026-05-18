from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from braintrust_harbor import (
    build_harbor_agents,
    default_agent_for_model,
    default_model_for_agent,
    env_list,
    matrix_conditions,
    matrix_named_items,
    matrix_targets,
    write_matrix_harbor_config,
)


class MatrixTests(unittest.TestCase):
    def test_env_list_parses_comma_separated_values(self) -> None:
        with patch.dict(os.environ, {"HARBOR_TARGETS": "codex, claude-code ,,gemini"}, clear=False):
            self.assertEqual(env_list("HARBOR_TARGETS"), ("codex", "claude-code", "gemini"))

    def test_default_agent_and_model_mapping(self) -> None:
        self.assertEqual(default_agent_for_model("anthropic/claude-sonnet-4-6"), "claude-code")
        self.assertEqual(default_agent_for_model("openai/gpt-5.4"), "codex")
        self.assertEqual(default_model_for_agent("claude-code"), "anthropic/claude-sonnet-4-6")
        self.assertEqual(default_model_for_agent("codex"), "openai/gpt-5.4")

    def test_matrix_targets_can_be_overridden_by_env(self) -> None:
        matrix = {"targets": [{"name": "disabled", "agent": "codex", "models": ["openai/gpt-5.4"], "enabled": False}]}
        with patch.dict(os.environ, {"HARBOR_AGENT": "claude-code", "HARBOR_MODEL": "anthropic/claude-sonnet-4-6"}, clear=False):
            targets = matrix_targets(matrix)

        self.assertEqual(targets, [{"name": "env-target", "agent": "claude-code", "agent_import_path": None, "models": ["anthropic/claude-sonnet-4-6"], "enabled": True}])

    def test_matrix_filters_enabled_items(self) -> None:
        matrix = {
            "conditions": [
                {"name": "snapshot", "enabled": True},
                {"name": "live", "enabled": False},
            ],
            "skill_variants": [
                {"name": "with-skill", "enabled": True},
                {"name": "no-skill", "enabled": True},
            ],
        }
        with patch.dict(os.environ, {"HARBOR_SKILL_VARIANTS": "no-skill"}, clear=False):
            self.assertEqual(matrix_conditions(matrix), [{"name": "snapshot", "enabled": True}])
            self.assertEqual(
                matrix_named_items(
                    matrix,
                    "skill_variants",
                    default_name="with-skill",
                    env_name="HARBOR_SKILL_VARIANTS",
                ),
                [{"name": "no-skill", "enabled": True}],
            )

    def test_build_harbor_agents_deduplicates_targets_and_sets_env_templates(self) -> None:
        targets = [
            {"name": "codex", "agent": "codex", "models": ["openai/gpt-5.4", "openai/gpt-5.4"]},
            {"name": "claude", "agent": "claude-code", "models": ["anthropic/claude-sonnet-4-6"]},
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "y"}, clear=True):
            matrix = build_harbor_agents(targets)

        self.assertEqual(matrix.missing_env, [])
        self.assertEqual(len(matrix.agents), 2)
        self.assertEqual(matrix.agents[0]["env"], {"OPENAI_API_KEY": "${OPENAI_API_KEY}"})
        self.assertEqual(matrix.agents[1]["env"], {"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"})

    def test_write_matrix_harbor_config_writes_expected_harbor_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.json"
            write_matrix_harbor_config(
                path=path,
                job_name="job",
                tasks_dir=Path(tmp) / "tasks",
                agents=[{"name": "codex", "model_name": "openai/gpt-5.4"}],
                defaults={"jobs_dir": "jobs", "max_concurrency": 8},
            )
            value = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(value["job_name"], "job")
        self.assertEqual(value["n_concurrent_trials"], 8)
        self.assertEqual(value["environment"], {"type": "docker"})
        self.assertEqual(value["agents"], [{"name": "codex", "model_name": "openai/gpt-5.4"}])


if __name__ == "__main__":
    unittest.main()
