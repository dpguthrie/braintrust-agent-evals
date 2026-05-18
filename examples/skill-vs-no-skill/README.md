# Skill Vs No Skill

Use this pattern when you want to measure whether a skill, rules file, MCP
server, or tool-specific guide actually improves coding-agent behavior.

Recommended Harbor representation:

```text
tasks/
  healthy-exit-with-skill/
  healthy-exit-no-skill/
  dataset-gap-with-skill/
  dataset-gap-no-skill/
```

Each directory is an ordinary Harbor task with its own `task.toml`,
`instruction.md`, `environment/`, and `tests/`. For `no-skill`, keep the same
fixtures and verifier, but remove the skill installation from the sandbox.

Then run them with a normal Harbor job config:

```yaml
job_name: skill-comparison
n_concurrent_trials: 8
environment:
  type: docker
datasets:
  - path: tasks
agents:
  - name: codex
    model_name: openai/gpt-5.4
  - name: claude-code
    model_name: anthropic/claude-sonnet-4-6
```

Use task metadata or a sidecar artifact to label rows with `scenario` and
`variant` when importing the Harbor job into Braintrust.

Useful scores:

- route correctness
- schema or handoff validity
- evidence before mutation
- tool-call order
- side-effect safety
- harness reliability
- cost/runtime efficiency
