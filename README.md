# Braintrust Harbor

Harbor-first, Braintrust-backed evaluation helpers for coding-agent tooling.

Use this package when you want to evaluate how coding agents interact with your
developer tools, CLIs, MCP servers, skills, repositories, or harness-specific
instructions.

## What This Does

This package is the bridge between Harbor and Braintrust:

- Harbor runs the agent trials in sandboxes.
- Braintrust stores experiment rows, traces, scores, comparisons, and analysis.
- `bt-harbor` runs one Harbor job or imports an existing Harbor job, then maps
  each Harbor trial to one Braintrust experiment row.

The intended flow is:

```text
Harbor tasks + JobConfig
  -> harbor run
  -> Harbor job artifacts
  -> bt-harbor import
  -> Braintrust experiment
```

## Prerequisites

You need:

- Python 3.11 or newer.
- The Harbor CLI available on `PATH`.
- A Harbor-supported sandbox backend, usually Docker for local examples.
- Model provider API keys required by the Harbor agents you run.
- `BRAINTRUST_API_KEY` only when using `--upload`. Local preview imports work
  without uploading.

Install this package from a checkout:

```bash
uv tool install -e .
```

Check the CLIs:

```bash
bt-harbor --help
harbor --version
```

After publishing, the package can also be run with:

```bash
uvx braintrust-harbor --help
```

## Quickstart

Start with the prompt + repo + harness/model + tooling-version workflow:

```bash
bt-harbor init harness-model-demo --template harness-model-matrix
cd harness-model-demo
```

Edit `eval-input.json` to choose:

- `prompt`: the user request the agent should complete.
- `repo.url` and `repo.ref`: optional repository to clone into the sandbox.
- `agents`: Harbor harness/model pairs.
- `tooling_versions`: labels and optional install commands for the tooling
  versions you want to compare.

Generate a Harbor suite for one tooling version:

```bash
python scripts/materialize.py \
  --input eval-input.json \
  --tooling-version current \
  --out generated/current
```

Run Harbor and write a local Braintrust import preview:

```bash
cd generated/current
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --metadata metadata.json \
  --scorer "scorers:summary_present" \
  --scorer "scorers:used_demo_tool" \
  --scorer "scorers:no_harbor_exception"
```

Add `--upload` to publish the imported rows to Braintrust:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --metadata metadata.json \
  --scorer "scorers:summary_present" \
  --scorer "scorers:used_demo_tool" \
  --scorer "scorers:no_harbor_exception" \
  --upload
```

## Core Concepts

Harbor concepts:

- A task is a directory with instructions, an environment, and verifier tests.
- A trial is one agent attempt at a task.
- A job is a collection of trials across tasks, datasets, agents, and models.

Braintrust concepts:

- An experiment is a comparable eval run.
- Each row represents one eval case. In this package, one Harbor trial becomes
  one Braintrust row.
- Scores are numeric checks added by Harbor rewards or Braintrust-compatible
  scorers.
- Traces preserve the trial trajectory, tool calls, command logs, and scorer
  spans when those artifacts are available.

This package does not replace Harbor's `JobConfig`, agent adapters, sandbox
management, or task format. It also does not impose your product's scoring
policy. Suites should keep product-specific prompts, fixtures, verifiers, and
scorers in their own task directories.

## Common Workflows

Run a Harbor job and import it:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json
```

Import a job that another system already ran:

```bash
bt-harbor import jobs/nightly-agent-tooling-run \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --upload
```

Add suite scorers:

```bash
bt-harbor import jobs/nightly-agent-tooling-run \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --scorer "my_suite.scorers:summary_present" \
  --scorer "my_suite.scorers:tool_order_quality" \
  --upload
```

Run on a schedule:

1. Keep the Harbor execution in CI, cron, or your scheduler.
2. Install the latest version of your tooling in the task environment.
3. Run `bt-harbor run ... --upload`, or run Harbor separately and then
   `bt-harbor import ... --upload`.
4. Compare Braintrust experiments by metadata such as `tooling_version`,
   `agent`, `model`, `scenario`, and `variant`.

## Examples

See [examples/README.md](examples/README.md) for the full examples guide.

- [harness-model-matrix](examples/harness-model-matrix/README.md):
  best first example for evaluating one prompt across optional repos,
  harness/model pairs, and tooling versions.
- [minimal-cli-tool](examples/minimal-cli-tool/README.md): smallest runnable
  template for a toy CLI, command logging, artifacts, and a verifier.
- [skill-vs-no-skill](examples/skill-vs-no-skill/README.md): task layout
  pattern for comparing a skill, MCP server, rules file, or guide against a
  control variant.
- [import-existing-harbor-job](examples/import-existing-harbor-job/README.md):
  import-only pattern for teams that already run Harbor elsewhere.

## Customization Checklist

For a real suite, customize these pieces:

- `harbor-job.json`: agents, models, concurrency, datasets, attempts, and
  environment backend.
- `tasks/*/instruction.md`: the user-facing task prompt.
- `tasks/*/environment/`: install your CLI, MCP server, skill, repo, or service.
- `tasks/*/tests/`: verify the agent produced the required behavior and reward.
- `.agent-tooling-eval.json`: row input, expected output, and metadata labels.
- `suite-artifacts.json`: extra trial artifacts to attach to Braintrust rows.
- `scorers.py`: Braintrust-compatible scorers for trajectory and output quality.

Useful metadata dimensions are `tooling_version`, `scenario`, `variant`,
`agent`, `model`, `repo_ref`, and any feature flag names you are comparing.

## External Documentation

Harbor:

- [Core concepts](https://www.harborframework.com/docs/core-concepts)
- [Task structure](https://www.harborframework.com/docs/tasks)
- [Run jobs](https://www.harborframework.com/docs/run-jobs)
- [Agents](https://www.harborframework.com/docs/agents)

Braintrust:

- [Evaluate systematically](https://www.braintrust.dev/docs/evaluate)
- [Run experiments](https://www.braintrust.dev/docs/evaluate/run-evaluations)
- [Interpret evaluation results](https://www.braintrust.dev/docs/evaluate/interpret-results)
- [Examine traces](https://www.braintrust.dev/docs/observe/examine-traces)

Project docs:

- [Architecture](docs/architecture.md)
- [Scorers](docs/scorers.md)
- [Compatibility](docs/compatibility.md)
- [Releasing](docs/releasing.md)

## Library API

```python
from braintrust_harbor import (
    HarborBatchConfig,
    SuiteArtifactConfig,
    import_harbor_job_to_braintrust,
    run_harbor_batch,
)
```

The recommended integration point is still Harbor's native `JobConfig`:

```text
Harbor JobConfig -> one Harbor run -> one Braintrust experiment
```

If your suite needs extra dimensions such as "with skill" vs. "without skill",
generate ordinary Harbor task directories or datasets for those variants, then
point the Harbor job config at them.

## Status

This is an alpha extraction. The Harbor job import path and Braintrust upload
path are usable, but the CLI and normalized trace/event helpers should be
treated as evolving APIs until a stable release.
