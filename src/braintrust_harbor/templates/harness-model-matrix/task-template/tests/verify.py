from __future__ import annotations

import json
from pathlib import Path
import sys


ARTIFACTS = Path("/logs/artifacts")


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing artifact: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


summary = load_json(ARTIFACTS / "summary.json")
if not isinstance(summary, dict):
    fail("summary.json must contain an object")
if not isinstance(summary.get("recommendation"), str) or not summary["recommendation"].strip():
    fail("summary.json must include a non-empty recommendation string")
if not isinstance(summary.get("evidence"), list) or not summary["evidence"]:
    fail("summary.json must include a non-empty evidence list")

narrative_path = ARTIFACTS / "narrative.md"
if not narrative_path.exists() or not narrative_path.read_text(encoding="utf-8").strip():
    fail("narrative.md must exist and be non-empty")

command_log_path = ARTIFACTS / "command-log.jsonl"
if not command_log_path.exists():
    fail("command-log.jsonl must exist")
rows = []
for line in command_log_path.read_text(encoding="utf-8").splitlines():
    if line.strip():
        rows.append(json.loads(line))
if not any(isinstance(row, dict) and row.get("tool") == "demo-tool" for row in rows):
    fail("agent must call demo-tool at least once")

print(json.dumps({"ok": True, "checks": ["summary", "narrative", "demo-tool"]}))
