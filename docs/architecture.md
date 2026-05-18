# Architecture

## Ownership Boundaries

This package keeps three responsibilities separate.

Harbor owns:

- sandbox lifecycle
- coding-agent harness adapters
- model selection
- task execution
- trial concurrency
- verifier execution
- local job artifacts

Braintrust owns:

- experiment rows
- trace and span storage
- scores
- experiment comparison
- offline and uploaded analysis

The consuming suite owns:

- task and dataset generation
- prompts
- optional repos or fixtures
- tool/skill installation inside the Harbor task image
- verifier policy
- suite-specific scorers
- artifact contracts for product-specific outputs

This package owns only the bridge:

- run `harbor run --config ...`
- find the produced Harbor job directory
- load Harbor result files and configured suite artifacts
- build a best-effort offline normalized trace view
- run Braintrust-compatible scorers
- import one Harbor job as one Braintrust experiment

The package does not materialize product-specific tasks and does not define a
parallel matrix format. Use Harbor's native `JobConfig` for datasets, tasks,
agents, models, environment backends, concurrency, retries, artifacts, and
metrics. If a suite needs extra dimensions, such as a skill/no-skill comparison,
represent those dimensions as ordinary Harbor tasks or datasets and let Harbor
fan them out as trials.

## Job Mapping

The intended mapping is:

```text
one harbor run command -> one Braintrust experiment
one Harbor trial       -> one Braintrust experiment row
Harbor verifier score  -> row output/reward metadata and optional score input
ATIF / command logs    -> normalized Braintrust child spans
```

This keeps scale in Harbor and comparison in Braintrust. Braintrust does not
spawn each agent task; it receives the completed Harbor job and imports it.

## Trace Model

Imported rows get an `eval` root span and a `task` child span. Under the task
span, the importer logs reconstructed normalized spans for:

- the Harbor trial
- configured command-log rows
- ATIF agent messages
- ATIF tool calls
- Harbor step directories, when present

This is an offline import, not a live Harbor lifecycle integration. The importer
only sees files Harbor wrote to disk after a trial. Missing or nonstandard trace
artifacts are imported on a best-effort basis and labeled with
`trace_import_warnings` metadata.

The span names are display names. Scorers should prefer stable semantic metadata
when possible, such as `normalized_kind`, command classes, tool names, and
ordered events. Span names are still useful for trajectory-level checks, but
they should not be the only source of truth when scorers need to work across
multiple tracing integrations.

See [Tracing](tracing.md) for the trace contract, limitations, and the shape of
a better native Harbor lifecycle integration.

## Suite Artifacts

Harbor has a stable job layout, but your product-specific files are suite-owned.
Declare them with `SuiteArtifactConfig` or a JSON file:

```json
{
  "artifacts": [
    {"key": "summary", "paths": ["summary.json"], "kind": "json"},
    {"key": "narrative", "paths": ["narrative.md"], "kind": "text"},
    {"key": "command_log", "paths": ["command-log.jsonl"], "kind": "jsonl"}
  ],
  "command_log_key": "command_log",
  "command_span_prefix": "tool"
}
```

The importer looks inside each trial's `artifacts/`, `verifier/`, and `agent/`
directories and attaches configured files to row output.

## Online And Offline Scoring

Offline Harbor import uses `ImportedTrace`, a local trace-like adapter over the
normalized Harbor records. Online Braintrust scorers can receive Braintrust's
trace object directly. To make scorers portable, write them against the shared
subset:

```python
async def score(input=None, output=None, expected=None, metadata=None, trace=None):
    spans = await trace.get_spans(["tool"])
    ...
```

For trajectory order checks, use helper functions that canonicalize raw spans
into semantic events. This lets a scorer ask "did `bt.sql` happen before
`bt.eval_full`?" without depending on one harness's exact span naming scheme.
