# Harness Model Matrix

This template shows the workflow where a user supplies:

- one prompt
- an optional repository to clone into the task sandbox
- a matrix of Harbor harness/model pairs
- one or more versions of the tooling being evaluated

Harbor runs the agents. `bt-harbor` imports the completed Harbor job into
Braintrust so each trial can be compared by model, harness, task, and tooling
version.

## 1. Create The Example

From any checkout where `bt-harbor` is installed:

```bash
bt-harbor init harness-model-demo --template harness-model-matrix
cd harness-model-demo
```

Edit `eval-input.json`:

- `prompt`: the user request the agent should complete
- `repo.url` and `repo.ref`: optional; leave blank for the built-in toy repo
- `agents`: Harbor harness/model pairs to run
- `tooling_versions`: labels and optional install commands for the tool version
  under test

## 2. Materialize One Tooling Version

```bash
python scripts/materialize.py \
  --input eval-input.json \
  --tooling-version current \
  --out generated/current
```

The materializer writes an ordinary Harbor suite in `generated/current/`:

- `harbor-job.json`
- `metadata.json`
- `suite-artifacts.json`
- `scorers.py`
- `tasks/prompted-tooling-task/...`

## 3. Run Harbor And Import To Braintrust

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

Add `--upload` when you want to publish rows to Braintrust.

## 4. Compare Tooling Versions

If you are still in `generated/current`, return to the template root, then
materialize and run a second version:

```bash
cd ../..
python scripts/materialize.py \
  --input eval-input.json \
  --tooling-version latest \
  --out generated/latest
```

Run `bt-harbor` from `generated/latest/` with the same command. Braintrust will
then have separate experiments or experiment metadata for `current` and
`latest`, so regressions are visible by tooling version, harness, and model.

## 5. Use Harbor's Example Tasks

From the template root, use Harbor's `hello-mcp` and `hello-skills` examples by
cloning Harbor and using the alternate input file:

```bash
git clone https://github.com/harbor-framework/harbor.git /tmp/harbor
python scripts/materialize.py \
  --input eval-input.harbor-examples.json \
  --tooling-version latest \
  --out generated/harbor-examples
```

That copies `/tmp/harbor/examples/tasks/hello-mcp` and
`/tmp/harbor/examples/tasks/hello-skills`, appends the prompt overlay, and adds
Braintrust row metadata. For real suites, replace the example scorers with
checks that match your product's tool contracts.

## 6. Scheduled Regression Checks

The included `.github/workflows/harness-model-nightly.yml` is a starting
point for nightly runs. Fill in your Harbor install command, secrets, and the
`tooling_versions[].install_command` that installs the latest version of the
tooling you want to evaluate.
