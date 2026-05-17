# Minimal CLI Tool

Create this runnable example from the packaged template:

```bash
bt-harbor init minimal-cli-tool
cd minimal-cli-tool
bt-harbor run harbor-job.json \
  --project "agent-tooling-demo" \
  --suite-artifacts suite-artifacts.json
```

The generated task uses a fake `acme` CLI, records command calls, and verifies
that the agent wrote a summary without mutating source files.
