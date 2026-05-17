# Skill Vs No Skill

Use this pattern when you want to measure whether a skill, rules file, MCP
server, or tool-specific guide actually improves coding-agent behavior.

Recommended matrix dimensions:

```toml
[defaults]
scenarios = ["healthy-exit", "measurement-gap", "dataset-gap"]
max_concurrency = 8

[[skill_variants]]
name = "with-skill"
enabled = true

[[skill_variants]]
name = "no-skill"
enabled = true

[[targets]]
name = "codex"
agent = "codex"
models = ["openai/gpt-5.4"]

[[targets]]
name = "claude-code"
agent = "claude-code"
models = ["anthropic/claude-sonnet-4-6"]
```

The consuming suite should materialize one Harbor task directory per scenario
and skill variant. For `no-skill`, keep the same fixtures and verifier, but
remove the skill installation from the sandbox.

Useful scores:

- route correctness
- schema or handoff validity
- evidence before mutation
- tool-call order
- side-effect safety
- harness reliability
- cost/runtime efficiency
