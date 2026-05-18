# Minimal CLI Tool

Use this example when you want the smallest runnable suite that shows the full
Harbor-to-Braintrust loop.

The generated task gives the agent a fake `acme` CLI, records command calls, and
verifies that the agent writes a structured summary without mutating source
files.

## Run It

Create the runnable template:

```bash
bt-harbor init minimal-cli-tool
cd minimal-cli-tool
```

Run Harbor and create a local Braintrust import preview:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json
```

Add `--upload` when you want to publish the imported rows to Braintrust.

## What To Look At

- `harbor-job.json`: one Harbor job over the local `tasks/` dataset.
- `tasks/help-flow/instruction.md`: what the agent is asked to do.
- `tasks/help-flow/environment/`: the toy `acme` CLI and app files.
- `tasks/help-flow/tests/`: verifier script for the required artifacts.
- `suite-artifacts.json`: tells `bt-harbor` to import `summary.json`,
  `narrative.md`, and command logs.
- `scorers.py`: example Braintrust-compatible scorers.

## How To Modify It

Replace the toy `acme` CLI with your real developer tool, then update:

- `instruction.md` with the workflow agents should perform.
- `tests/verify.py` with checks that prove the workflow succeeded.
- `suite-artifacts.json` with the artifacts your tool or verifier writes.
- `scorers.py` with trajectory or output checks that matter for your tool.

Keep this example narrow. If you need prompt + repo input, multiple harnesses,
or versioned tooling comparisons, start from `harness-model-matrix`.
