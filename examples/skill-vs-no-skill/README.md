# Skill Vs No Skill

Use this pattern when you want to measure whether a skill, rules file, MCP
server, or tool-specific guide actually improves coding-agent behavior.

This is a task-layout pattern, not a packaged template. It is useful when the
main evaluation question is a controlled comparison:

```text
Does this added guidance or tool make agents more successful, more reliable, or
cheaper on the same task?
```

## Recommended Harbor Layout

Create paired Harbor tasks:

```text
tasks/
  healthy-exit-with-skill/
  healthy-exit-no-skill/
  dataset-gap-with-skill/
  dataset-gap-no-skill/
```

Each directory is an ordinary Harbor task with its own `task.toml`,
`instruction.md`, `environment/`, and `tests/`.

For each pair:

- Keep fixtures, prompt intent, and verifier criteria the same.
- In `with-skill`, install the skill, MCP server, rules file, or guide.
- In `no-skill`, remove only that added guidance or tool.
- Label the rows with metadata such as `scenario` and `variant`.

## Example Harbor Job

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

Run and import with:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json \
  --scorer "scorers:variant_quality"
```

## Useful Scores

- Route correctness.
- Schema or handoff validity.
- Evidence before mutation.
- Tool-call order.
- Side-effect safety.
- Harness reliability.
- Cost and runtime efficiency.

## How To Modify It

Use this pattern for any A/B agent-tooling comparison:

- `with-mcp` vs. `no-mcp`
- `with-rules` vs. `no-rules`
- `new-tool-version` vs. `old-tool-version`
- `strict-system-prompt` vs. `default-system-prompt`

Keep variants as close as possible. If several things change at once, the
Braintrust comparison will show a difference but not explain what caused it.
