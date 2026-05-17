# Releasing

Braintrust Harbor publishes to PyPI from GitHub Releases.

## One-Time PyPI Setup

Use PyPI Trusted Publishing rather than a long-lived API token.

Create or claim the `braintrust-harbor` project on PyPI, then add a GitHub
trusted publisher with:

- Owner: the GitHub organization or user that owns the repo
- Repository name: `braintrust-harbor` or the actual GitHub repo name
- Workflow name: `publish.yml`
- Environment name: `pypi`

The publish workflow uses GitHub OIDC through `id-token: write`; it does not
need a `PYPI_API_TOKEN` secret.

## GitHub Setup

Create a GitHub environment named `pypi`.

Recommended environment rules:

- require reviewer approval for publishing
- restrict deployment branches/tags if your org policy supports it

## Release Flow

1. Update `version` in `pyproject.toml`.
2. Merge the release commit to `main`.
3. Create a GitHub release whose tag exactly matches the package version:

   ```bash
   gh release create v0.1.0a1 \
     --repo <owner>/<repo> \
     --title "v0.1.0a1" \
     --notes "Initial alpha release."
   ```

4. The `Publish to PyPI` workflow builds, tests, checks that the release tag
   matches `pyproject.toml`, and publishes the sdist/wheel to PyPI.

For the current package version, the release tag should be:

```text
v0.1.0a1
```

## Local Build Check

Before creating a release:

```bash
uv sync --extra dev
uv run pytest
uv build
```

The generated files in `dist/` are ignored and should not be committed.
