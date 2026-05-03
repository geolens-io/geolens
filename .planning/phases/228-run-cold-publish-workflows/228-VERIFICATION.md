# Phase 228 - VERIFICATION

**Verified:** 2026-05-03  
**Phase:** 228-run-cold-publish-workflows  
**Status:** PUBLISH-01..04 satisfied

---

## PUBLISH-01: release credentials and Trusted Publishing

**GitHub secrets:**

```text
$ gh secret list --repo geolens-io/geolens | grep -E '^(NPM_TOKEN|PYPI_TOKEN|GEOLENS_ENTERPRISE_TOKEN)' || true
GEOLENS_ENTERPRISE_TOKEN  2026-04-30T10:59:00Z
NPM_TOKEN                 2026-05-02T23:47:31Z
```

- `NPM_TOKEN`: present.
- `PYPI_TOKEN`: absent, by design. PyPI publishes use GitHub Actions OIDC Trusted Publishing.
- `GEOLENS_ENTERPRISE_TOKEN`: present, pre-existing, unrelated to package publishing.

**Trusted Publisher configuration used for the successful publishes:**

- `geolens`: repository `geolens-io/geolens`, workflow `publish-sdks.yml`, environment blank.
- `geolens-cli`: repository `geolens-io/geolens`, workflow `publish-cli.yml`, environment blank.

---

## PUBLISH-02: SDK publish workflows completed

**Workflow runs:**

- SDK dry-run: https://github.com/geolens-io/geolens/actions/runs/25266579270
- SDK first live attempt: https://github.com/geolens-io/geolens/actions/runs/25266623747 - failed before upload due PyPI publisher scope mismatch.
- SDK live publish: https://github.com/geolens-io/geolens/actions/runs/25266789877

**Registry confirmation:**

```text
$ python -m pip index versions geolens
geolens (1.0.0)
Available versions: 1.0.0, 0.0.0

$ npm view @geolens/sdk version --json
"1.0.0"
```

**Final public install names:**

- Python SDK: `geolens`
- TypeScript SDK: `@geolens/sdk`

---

## PUBLISH-03: CLI publish workflow completed

**Workflow runs:**

- CLI dry-run: https://github.com/geolens-io/geolens/actions/runs/25266579277
- CLI live publish: https://github.com/geolens-io/geolens/actions/runs/25266798787

**Registry confirmation:**

```text
$ python -m pip index versions geolens-cli
geolens-cli (1.0.0)
Available versions: 1.0.0
```

The PyPI distribution is `geolens-cli`; the executable command remains `geolens`.

---

## PUBLISH-04: clean-machine install verification

**Workflow run:**

- Verify Published Packages: https://github.com/geolens-io/geolens/actions/runs/25266870449
- Conclusion: success

The verifier ran without local checkout context:

```text
docker run --rm python:3.13-slim
  pip install --no-cache-dir geolens geolens-cli
  geolens --version
  python -c 'from geolens import GeolensClient; print(GeolensClient)'

docker run --rm node:22-slim
  mkdir -p /tmp/geolens-sdk-smoke
  npm init -y
  npm install --no-save @geolens/sdk
  node -e 'import("@geolens/sdk").then(...)'
```

The TypeScript verifier was fixed in commit `424ebdc3` after the first run exposed an npm root-directory install issue. The package itself installed and imported successfully in a manual clean temp-dir Docker smoke before the workflow fix.

---

## PyPI cleanup status

`geolens-sdk` is not a published PyPI package:

```text
$ python -m pip index versions geolens-sdk
ERROR: No matching distribution found for geolens-sdk
```

If a stale `geolens-sdk` pending publisher still appears in PyPI account settings, remove it. There is no live release to yank.
