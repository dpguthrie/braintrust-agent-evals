# Tracing

`braintrust-harbor` currently provides an offline Harbor-to-Braintrust trace
importer. It does not hook into Harbor's live eval lifecycle.

## What Happens Today

The import path is:

```text
Harbor runs a job
  -> Harbor writes job/trial artifacts
  -> bt-harbor reads the completed job directory
  -> bt-harbor reconstructs Braintrust rows and spans
```

This is intentionally different from native instrumentation. We do not create
Braintrust spans while Harbor is setting up sandboxes, executing agents, or
running verifiers. Instead, we reconstruct the trace from files Harbor persisted
after the trial.

## Imported Span Shape

Each Harbor trial becomes one Braintrust experiment row. In upload mode the
importer creates:

```text
eval
  task
    harbor.trial
    tool.<command_class>        # only when configured suite command logs exist
    agent.context              # from ATIF system/user/environment steps
    agent.message              # from ATIF agent steps
    agent.tool.<tool_name>      # from ATIF tool calls
    harbor.step.<step_name>    # for Harbor multi-step task directories
  <scorer span>
```

Span names are display names. Scorers should prefer semantic metadata such as
`normalized_kind`, `command_class`, `tool_name`, `step_name`, `agent`, and
`model`.

## Data Sources

The importer reads:

- job-level `config.json` and `result.json`
- trial-level `config.json` and `result.json`
- optional `agent/trajectory.json` or `artifacts/trajectory.json`
- optional `agent/atif.json` or `artifacts/atif.json`
- optional verifier rewards under `verifier/`
- optional suite-owned files under `artifacts/`, `verifier/`, or `agent/`
- optional Harbor multi-step runtime directories under `steps/`

Suite-owned files are declared in `suite-artifacts.json`. Command spans are only
created when a suite declares a command-log artifact with `command_log_key`.

## ATIF Handling

Harbor's Agent Trajectory Interchange Format is the best source of agent
messages, tool calls, observations, and token/cost metrics. The importer handles
ATIF-like dictionaries defensively:

- `schema_version` should start with `ATIF-v1.`
- `steps` should be a list
- step `source` values are expected to be `agent`, `system`, `user`, or
  `environment`
- `tool_calls`, when present, should be a list
- tool-call observations are matched by `tool_call_id` to
  `observation.results[].source_call_id` when possible

Any nonstandard shape is imported on a best-effort basis and recorded in
`trace_import_warnings` metadata.

## Known Limitations

- This is not live lifecycle logging. If Harbor crashes before writing trial
  artifacts, Braintrust may have no row or only a partial reconstructed row.
- Setup, teardown, and verifier timing are only as precise as the timestamps
  Harbor writes.
- Tool-call timing is approximated from ATIF step timestamps. Individual tool
  start/end times are not available unless the agent or suite writes them.
- Command-log spans are suite-owned, not Harbor-owned.
- Trial discovery still depends on Harbor's job directory layout.
- We preserve the raw `trajectory_path` in imported output/metadata, but do not
  upload the raw file contents as an attachment.

## Better Long-Term Integration

A native integration would require stable Harbor lifecycle hooks or an event
stream. Useful events would include:

- `job_started` / `job_completed`
- `trial_started` / `trial_completed`
- `environment_setup_started` / `environment_setup_completed`
- `agent_started` / `agent_completed`
- `trajectory_step_logged`
- `tool_call_started` / `tool_call_completed`
- `verifier_started` / `verifier_completed`

With those hooks, Braintrust could create and close spans during the actual
Harbor run instead of reconstructing them afterward. Until then,
`bt-harbor import` should be treated as a pragmatic offline bridge.
