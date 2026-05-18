# Braintrust Harbor

Harbor-first, Braintrust-backed evaluation helpers for coding-agent tooling.

This package is for teams that want to evaluate how coding agents interact with
their developer tools, CLIs, MCP servers, skills, repos, or harness-specific
instructions.

The core model is intentionally simple:

- Harbor owns sandboxed agent execution, harness adapters, models, and
  concurrency.
- Braintrust owns experiments, imported traces, scores, comparison, and
  analysis.
- This package is the bridge: it runs one Harbor job and imports each Harbor
  trial as one Braintrust experiment row.

## Install

From a checkout:

```bash
uv tool install -e .
```

After publishing:

```bash
uvx braintrust-harbor --help
```

The CLI entrypoints are:

```bash
braintrust-harbor --help
bt-harbor --help
```

## Why Harbor Is External

Harbor is not vendored into this package because Harbor is the execution engine,
not a helper library here. It owns sandbox provisioning, built-in coding-agent
adapters, model execution, retries, job layout, and concurrency. Keeping it as a
separate CLI dependency means teams can use Harbor exactly as documented,
including their preferred Harbor version and environment backend.

This package only requires that `harbor` is available on `PATH` when you run a
job:

```bash
harbor --version
```

If Harbor changes its job layout or CLI flags, update the package compatibility
range and tests rather than hiding that coupling behind a vendored copy.

## Quickstart

Create a minimal suite:

```bash
bt-harbor init my-tool-evals
cd my-tool-evals
```

Run Harbor and write a local Braintrust import preview:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json
```

Upload to Braintrust:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --upload
```

Import an existing Harbor job:

```bash
bt-harbor import jobs/my-harbor-job \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --upload
```

Add suite scorers:

```bash
bt-harbor import jobs/my-harbor-job \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --scorer "my_suite.scorers:summary_present" \
  --scorer "my_suite.scorers:inspect_before_change" \
  --upload
```

## Package Surface

Library APIs:

```python
from braintrust_harbor import (
    HarborBatchConfig,
    RunAndImportConfig,
    SuiteArtifactConfig,
    build_harbor_agents,
    import_harbor_job_to_braintrust,
    load_toml_matrix,
    run_harbor_batch,
    run_and_import,
    write_matrix_harbor_config,
)
```

The package includes optional matrix helpers for the common pattern:

```text
suite matrix -> generated Harbor job config -> one Harbor run -> one Braintrust experiment
```

The consuming suite still owns task materialization, fixtures, artifact names,
and domain scorers.

See:

- [Architecture](docs/architecture.md)
- [Scorers](docs/scorers.md)
- [Compatibility](docs/compatibility.md)
- [Releasing](docs/releasing.md)
- [Examples](examples/README.md)

## Status

This is an alpha extraction. The Harbor job import path and Braintrust upload
path are usable, but the CLI and normalized trace/event helpers should be
treated as evolving APIs until a stable release.
