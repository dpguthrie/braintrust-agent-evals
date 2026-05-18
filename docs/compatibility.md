# Compatibility

## Python

The package targets Python 3.11 and newer.

CI currently runs tests on:

- Python 3.11
- Python 3.12
- Python 3.13

## Braintrust

`braintrust>=0.18.0` is declared as a package dependency because upload mode and
Braintrust-compatible scorer behavior depend on the SDK. The importer checks the
installed SDK behavior in tests and avoids relying on private APIs where a public
shape is available.

If you are debugging SDK compatibility, inspect the SDK installed in your active
environment:

```bash
python -c "import braintrust, inspect; print(braintrust.__file__)"
```

## Harbor

Harbor is treated as an external CLI dependency. This package shells out to:

```bash
harbor run --config <path> --job-name <name>
```

The importer expects a Harbor job directory with trial `result.json`,
`config.json`, optional `agent/trajectory.json`, optional `agent/atif.json`,
optional `verifier/reward.json`, optional `artifacts/`, and optional `steps/`.

This package should not subclass or replace Harbor's built-in agents. If a team
needs a custom harness, implement a Harbor agent adapter and reference it from
the Harbor job config.

## Trace Contract

The normalized import trace currently uses:

- `harbor.trial`
- `harbor.step.<name>`
- `agent.message`
- `agent.tool.<tool>`
- configured command spans such as `tool.inspect`

These names are display-oriented and may evolve before a stable release. Scorers
that need online/offline portability should classify spans by semantic metadata
and command/tool attributes, not only by exact display name.

This is a best-effort offline import contract. It is not a guarantee that every
Harbor lifecycle event appears as a Braintrust span. Nonstandard ATIF shapes are
preserved where possible and recorded in `trace_import_warnings` metadata.
