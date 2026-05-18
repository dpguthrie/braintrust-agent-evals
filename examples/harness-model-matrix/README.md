# Harness Model Matrix

Use this example when you want to evaluate a workflow like:

```text
one user prompt
+ optional repo
+ several Harbor harness/model pairs
+ one or more tooling versions
= comparable Braintrust experiments
```

This is the best starting point for checking how the same task behaves across
agent harnesses, models, harness prompts, and versions of your own tooling.

## Run It

Create the packaged template:

```bash
bt-harbor init harness-model-demo --template harness-model-matrix
cd harness-model-demo
```

Materialize one tooling version:

```bash
python scripts/materialize.py \
  --input eval-input.json \
  --tooling-version current \
  --out generated/current
```

Run Harbor and import the job into a local Braintrust preview:

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

Add `--upload` when you want to publish the rows to Braintrust.

## What The Template Gives You

- `eval-input.json`: user-facing config for prompt, optional repo,
  harness/model pairs, and tooling versions.
- `scripts/materialize.py`: converts one tooling version into a normal Harbor
  suite under `generated/<version>/`.
- `task-template/`: default Harbor task with a toy `demo-tool` CLI.
- `eval-input.harbor-examples.json`: optional config for copying Harbor's
  `hello-mcp` and `hello-skills` tasks.
- `.github/workflows/harness-model-nightly.yml`: starter nightly workflow.

## How To Modify It

Edit `eval-input.json` first:

- Change `prompt` to the workflow you want agents to complete.
- Set `repo.url` and `repo.ref` if the task should run against a real repo.
- Add or remove entries under `agents` for the Harbor harness/model matrix.
- Add entries under `tooling_versions` for `current`, `latest`, feature-flagged
  builds, or pinned SHAs.
- Set each version's `install_command` to install the tooling under test in the
  task image.

Then update the generated suite pieces as needed:

- `task-template/environment/`: install your real CLI, MCP server, skill, or
  service.
- `task-template/tests/verify.py`: check the behavior that proves the agent used
  the tooling correctly.
- `suite-artifacts.json`: import any artifacts your tool or verifier writes.
- `scorers.py`: add Braintrust-compatible scores for output quality,
  trajectory quality, safety, cost, or runtime.

## Harbor Example Tasks

To reuse Harbor's `hello-mcp` and `hello-skills` examples:

```bash
git clone https://github.com/harbor-framework/harbor.git /tmp/harbor
python scripts/materialize.py \
  --input eval-input.harbor-examples.json \
  --tooling-version latest \
  --out generated/harbor-examples
```

The materializer copies those Harbor tasks, appends your prompt overlay, and
adds `.agent-tooling-eval.json` metadata so Braintrust can group results by
scenario and feature.

## Scheduled Use

For nightly checks:

1. Configure the GitHub Actions workflow to install Harbor.
2. Set model provider and Braintrust secrets.
3. Make the `latest` tooling version install the latest build of your tool.
4. Run the workflow on a schedule and compare Braintrust experiments by
   `tooling_version`, `agent`, `model`, and `scenario`.
