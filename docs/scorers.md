# Scorers

Scorers can be ordinary Braintrust-style callables. The importer passes:

- `input`
- `output`
- `expected`
- `metadata`
- `trace`

Example output-level scorer:

```python
def summary_present(output, **_kwargs):
    summary = output.get("summary")
    return {
        "name": "Summary present",
        "score": 1.0 if isinstance(summary, dict) else 0.0,
    }
```

Example trajectory-level scorer:

```python
async def smoke_before_full_eval(trace=None, **_kwargs):
    spans = await trace.get_spans(["tool"])
    command_classes = [
        (getattr(span, "metadata", None) or {}).get("command_class")
        for span in spans
    ]
    smoke = next((i for i, name in enumerate(command_classes) if name == "eval_smoke"), None)
    full = next((i for i, name in enumerate(command_classes) if name == "eval_full"), None)
    ok = full is None or (smoke is not None and smoke < full)
    return {
        "name": "Smoke before full eval",
        "score": 1.0 if ok else 0.0,
        "metadata": {"command_classes": command_classes},
    }
```

Span names are allowed as a signal, especially for trajectory checks, but prefer
canonical helper functions when your scorer must run across native Braintrust
traces and imported Harbor traces.

Use CLI scorer references like this:

```bash
bt-harbor import jobs/my-job \
  --project my-tool \
  --suite-artifacts suite-artifacts.json \
  --scorer "my_suite.scorers:summary_present" \
  --scorer "my_suite.scorers:smoke_before_full_eval"
```
