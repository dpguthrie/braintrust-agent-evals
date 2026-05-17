# Import Existing Harbor Job

If another system already owns Harbor execution, use this package only as the
Braintrust importer:

```bash
bt-harbor import jobs/nightly-agent-tooling-run \
  --project "my-developer-tool" \
  --experiment-name "nightly-agent-tooling-run" \
  --suite-artifacts suite-artifacts.json \
  --scorer "my_suite.scorers:trajectory_quality" \
  --upload
```

This mode is useful for scheduled infrastructure where Harbor runs at scale and
Braintrust receives the completed job for scoring and analysis.
