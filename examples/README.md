# Examples

The examples are meant to answer three questions:

- What kind of agent-tooling eval should I build?
- What files do I edit?
- How do I get results into Braintrust?

## Which Example Should I Start With?

| Example | Use Case | How To Run |
| --- | --- | --- |
| [harness-model-matrix](harness-model-matrix/README.md) | Evaluate one prompt across optional repos, harness/model pairs, and tooling versions. Best first stop for the workflow this package is built around. | `bt-harbor init harness-model-demo --template harness-model-matrix` |
| [minimal-cli-tool](minimal-cli-tool/README.md) | Learn the smallest runnable Harbor task with a toy CLI, command logs, suite artifacts, and verifier checks. | `bt-harbor init minimal-cli-tool` |
| [skill-vs-no-skill](skill-vs-no-skill/README.md) | Compare whether a skill, MCP server, rules file, or guide improves agent behavior against a control variant. | Build paired Harbor task directories, then run one Harbor job over `tasks/`. |
| [import-existing-harbor-job](import-existing-harbor-job/README.md) | Use Braintrust import/scoring when another scheduler or service already runs Harbor. | `bt-harbor import jobs/<job-name> ...` |

## What The Examples Have In Common

Each runnable example follows the same shape:

```text
harbor-job.json
suite-artifacts.json
scorers.py
tasks/
  <scenario>/
    task.toml
    instruction.md
    .agent-tooling-eval.json
    environment/
    tests/
```

The Harbor files define what the agent does and how the sandbox runs. The
Braintrust Harbor files define what to import, how to label rows, and what extra
scores to compute.

## How To Modify An Example

Start with the smallest change that tests your actual tool contract:

- Change `instruction.md` or `eval-input.json` to reflect the real user request.
- Put your CLI, MCP server, skill, or service setup in `environment/`.
- Keep verifiers in `tests/` focused on observable behavior.
- Add metadata in `.agent-tooling-eval.json` for dimensions you want to group by
  in Braintrust, such as `scenario`, `variant`, `tooling_version`, or feature
  flag.
- Add suite-specific artifacts to `suite-artifacts.json` if the agent writes
  summaries, command logs, plans, diffs, or structured handoff files.
- Add scorers for behavior that should be comparable across agents and harnesses.

The examples intentionally avoid product-specific scoring policy. Real suites
should add their own verifiers and Braintrust-compatible scorers.
