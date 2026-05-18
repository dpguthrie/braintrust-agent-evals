# Import Existing Harbor Job

Use this example when another system already owns Harbor execution and this
package should only handle Braintrust import, scoring, and analysis.

This is common for scheduled infrastructure:

- Harbor runs at scale in CI, cron, or an internal job runner.
- The Harbor job directory is persisted as an artifact.
- `bt-harbor import` turns that completed job into a Braintrust experiment.

## Run It

```bash
bt-harbor import jobs/nightly-agent-tooling-run \
  --project "my-developer-tool" \
  --experiment-name "nightly-agent-tooling-run" \
  --suite-artifacts suite-artifacts.json \
  --metadata metadata.json \
  --scorer "my_suite.scorers:trajectory_quality" \
  --upload
```

Omit `--upload` to write a local preview JSON file while developing scorers or
artifact mappings.

## What To Provide

- `jobs/nightly-agent-tooling-run`: completed Harbor job directory.
- `suite-artifacts.json`: suite-owned files to attach from each trial.
- `metadata.json`: optional experiment-level metadata such as tooling channel,
  git SHA, or scheduler run ID.
- `--scorer`: optional Braintrust-compatible scorer references.

## How To Modify It

For scheduled regression checks, attach metadata that makes comparisons easy:

- `tooling_version`
- `tooling_git_sha`
- `harbor_version`
- `dataset_version`
- `agent_harness`
- `model`
- `schedule_name`

Use stable experiment names if you want a predictable dashboard, or include a
timestamp/build ID if each scheduled run should be a separate named experiment.
