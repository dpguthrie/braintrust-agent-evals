# Minimal CLI Tool Eval

This template evaluates whether a coding agent can inspect a toy developer CLI,
produce a handoff artifact, and avoid mutating source files.

Run from this directory:

```bash
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json
```

Add `--upload` when you want to write the imported Harbor job to Braintrust.

The template intentionally keeps the fake tool simple. Replace `tasks/*` with
your own Harbor tasks, task environments, verifiers, and suite-specific scorers.
