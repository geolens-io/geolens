# GeoLens SDKs

Auto-generated client libraries for the GeoLens API, in Python and TypeScript.

Both SDKs are derived from `backend/openapi.json` (the canonical OpenAPI 3.1 snapshot of the FastAPI app) and published under the Apache-2.0 license.

| SDK | Package | Source | License |
|-----|---------|--------|---------|
| Python | `geolens` (PyPI) | `sdks/python/` | Apache-2.0 |
| TypeScript | `@geolens/sdk` (npm) | `sdks/typescript/` | Apache-2.0 |

## Installation

### Python

```bash
pip install geolens
# or with uv: uv add geolens
```

Requires Python 3.10+. Runtime dependencies: `httpx`, `attrs`, `python-dateutil`.

> The Python SDK package is `geolens`. Do not use the abandoned pre-pivot name `geolens-sdk`.

### TypeScript / JavaScript

```bash
npm install @geolens/sdk
# or: pnpm add @geolens/sdk
# or: yarn add @geolens/sdk
```

Requires Node 18+ (for native `fetch`). Single runtime dependency: `@hey-api/client-fetch`.

## Quickstart

### Python

```python
from geolens import GeolensClient
from geolens.api.search import (
    search_datasets_endpoint_search_datasets_get,
)

# Bearer-token auth (JWT)
client = GeolensClient(
    base_url="https://geolens.example.com",
    bearer_token="<JWT>",
)

# Use asyncio_detailed for in-process / ASGI tests; sync_detailed works
# against any real HTTP endpoint.
response = search_datasets_endpoint_search_datasets_get.sync_detailed(
    client=client.client,
    body=None,                              # see "Optional GET bodies" below
)
print(response.status_code)                 # 200
datasets = response.parsed                  # attrs dataclass (NOT pydantic)
print(datasets.to_dict())                   # serialize as dict
```

Switching to API-key auth:

```python
client = GeolensClient(
    base_url="https://geolens.example.com",
    api_key="<KEY>",                        # sent as X-API-Key header
)
# Or swap auth on an existing client:
client.set_api_key("<KEY>")
client.set_bearer_token("<JWT>")
```

The generated models are `attrs`-based dataclasses, **not** pydantic models. To deserialize a dict into a model:

```python
from geolens.models import DatasetResponse

payload = {"id": "...", "name": "..."}
dataset = DatasetResponse.from_dict(payload)
payload_back = dataset.to_dict()
```

> Note: pydantic v2 methods (`model_validate`, `model_dump`) are NOT available — `openapi-python-client` emits attrs dataclasses, not pydantic models. Use `.from_dict()` / `.to_dict()` instead.

Manifest apply is part of the generated Python SDK contract. Use
`geolens.api.datasets.apply_manifest_endpoint_ingest_manifest_apply_post` with
`ManifestApplyRequest` and `ManifestApplyResponse` models for
`POST /ingest/manifest/apply`.

### TypeScript

```typescript
import { createGeolensClient } from '@geolens/sdk';
import {
  searchDatasetsEndpointSearchDatasetsGet,
} from '@geolens/sdk';

const sdk = createGeolensClient({
  baseUrl: 'https://geolens.example.com',
  bearerToken: '<JWT>',
});

const { data, error, response } =
  await searchDatasetsEndpointSearchDatasetsGet({ client: sdk.client });

if (error) console.error(error);
else console.log(response.status, data);
```

Switching to API-key auth:

```typescript
const sdk = createGeolensClient({
  baseUrl: 'https://geolens.example.com',
  apiKey: '<KEY>',                          // sent as X-API-Key header
});
```

Manifest apply is exported from the generated TypeScript SDK as
`applyManifestEndpointIngestManifestApplyPost`, with
`ManifestApplyRequest` and `ManifestApplyResponse` types.

## Why these generators?

| Choice | Why |
|--------|-----|
| **`openapi-python-client@0.28.3`** for Python | Modern, actively maintained (2024-2026), runs via `uvx` (no global install), emits idiomatic typed clients backed by `httpx` (async-ready) and `attrs` dataclasses. Avoids the JVM dependency that `openapi-generator` (Java) imposes. |
| **`@hey-api/openapi-ts@0.96.1`** for TypeScript | Active replacement for the maintenance-mode `openapi-typescript-codegen`. ESM-only (Node 22+ for codegen), customizable templates, integrated client variants. Pairs with **`@hey-api/client-fetch@0.13.1`** for native `fetch` support. |

Alternatives considered and rejected: `openapi-generator-cli` (JVM dependency), `openapi-typescript-codegen` (legacy, maintenance-only), `Speakeasy` (commercial SaaS — incompatible with open-core ethos).

## Regeneration

Both SDKs are regenerated from `backend/openapi.json` via a single command from the repo root:

```bash
make sdks
```

This:
1. Re-snapshots `backend/openapi.json` (idempotent — same as `make openapi`).
2. Runs `scripts/flatten_openapi_defs.py` to rewrite OpenAPI 3.1 inline `$defs` references into `#/components/schemas/...` form. The committed snapshot is left intact; only the generators consume the flattened intermediate.
3. cp-stashes the hand-written `auth.py`, `__init__.py`, `auth.ts`, and `index.ts` to `/tmp` so the generators' `--overwrite` cannot delete them.
4. Runs `openapi-python-client@0.28.3` to overwrite `sdks/python/geolens/`.
5. Runs `@hey-api/openapi-ts@0.96.1` to overwrite `sdks/typescript/src/client/`.
6. Restores the cp-stashed hand-written files.
7. Runs `scripts/sync_sdk_versions.py` to copy `backend/openapi.json` `info.version` into both SDK package metadata files.

Hand-written files preserved across regeneration:

- `sdks/python/geolens/auth.py` (the `GeolensClient` wrapper)
- `sdks/python/geolens/__init__.py` (re-exports `GeolensClient`)
- `sdks/typescript/src/auth.ts` (the `createGeolensClient` factory)
- `sdks/typescript/src/index.ts` (public package re-exports)
- Both `pyproject.toml` / `package.json` (only the `version` field is rewritten by the sync script)
- Both `LICENSE` and `README.md` files

## Drift gate

The CI workflow runs `make sdks-check` on every backend-touching PR (job: `sdks-check` in `.github/workflows/ci.yml`):

```bash
make sdks-check
```

This regenerates both SDKs and fails if the result differs from what's committed (excluding the hand-written wrappers and READMEs via `git diff`'s `:!` pathspecs). Mirrors the existing `make openapi-check` pattern.

Locally, run the round-trip integration test:

```bash
make sdks-test
```

This exercises both SDKs against the in-process FastAPI app (Python: `httpx.ASGITransport`; TypeScript: a uvicorn subprocess on a free port) and confirms three endpoints round-trip with both Bearer-token and API-key auth.

> **Test-matrix note:** The `backend-test` CI job exercises the Python half of the round-trip suite (4 round-trip tests + 7 unit tests). The TypeScript subprocess test currently skips in `backend-test` because that job does not install Node; the dedicated `sdks-check` job catches TypeScript-side regeneration drift, and full TS round-trip is exercised locally via `make sdks-test`.

## Version-pin policy

SDK versions are **lockstep with the backend OpenAPI snapshot**.

The version in `backend/openapi.json` `info.version` (currently `1.0.2`) is the canonical source. `scripts/sync_sdk_versions.py`, run as part of `make sdks`, propagates this to:

- `sdks/python/pyproject.toml` `[project] version`
- `sdks/python/.openapi-python-client.yaml` `package_version_override`
- `sdks/typescript/package.json` `.version`

This means SDK 1.4.2 always corresponds to backend 1.4.2 — no version skew, no separate semver clock for SDKs. If you need to consume an older backend with a newer SDK (or vice versa), open an issue describing the use case; we'll consider it as a future requirement.

## Publishing

SDK publishing is manual-triggered through GitHub Actions. PyPI uses Trusted Publishing (OIDC), so there is no long-lived `PYPI_TOKEN` secret. npm uses the repository `NPM_TOKEN` secret until npm trusted publishing is GA for this package. The first public release shipped as `geolens==1.0.0` and `@geolens/sdk==1.0.0`; patch releases follow the OpenAPI lockstep version.

### One-time setup (user actions)

1. **PyPI Trusted Publisher for `geolens`:** project `geolens`, owner `geolens-io`, repository `geolens`, workflow `publish-sdks.yml`, environment blank.
2. **Claim the `@geolens` npm organization** at <https://www.npmjs.com/org/create>. The org must exist before publishing `@geolens/sdk`.
3. **Create an npm granular access token** with Read/Write and Bypass 2FA enabled, scoped to the `@geolens` org. Add it to the GitHub repository secrets as `NPM_TOKEN`.

### Publishing via the GitHub Actions workflow

The `Publish SDKs` workflow (`.github/workflows/publish-sdks.yml`) is manual-trigger only:

1. Navigate to **Actions → Publish SDKs → Run workflow** in the GitHub UI.
2. Choose the target: `python`, `typescript`, or `both`.
3. Optionally check `dry_run` to verify the build without publishing.
4. Click **Run workflow**.

The workflow:

- For Python: `uv build` produces a wheel + sdist in `sdks/python/dist/`; `uv publish --trusted-publishing automatic` uploads to PyPI through GitHub Actions OIDC.
- For TypeScript: `npm ci && npm run build` produces compiled JS + type declarations in `sdks/typescript/dist/`; `npm publish --access public` uploads to npm using `NODE_AUTH_TOKEN`.

### Publishing locally (alternative)

If you prefer to publish from your workstation:

```bash
# Python — prefer the GitHub Actions Trusted Publishing workflow for release
cd sdks/python
uv build

# TypeScript — requires npm login or NPM_TOKEN
cd sdks/typescript
npm install
npm run build
npm publish --access public  # --access public REQUIRED for first publish of @scope/name
```

The `--access public` flag is required for scoped npm packages because scoped packages default to private (paid org tier required for private). The `package.json` already includes `"publishConfig": { "access": "public" }` as a belt-and-suspenders measure.

## Known rough edges (1.x)

### Verbose function names

FastAPI auto-generates `operationId`s by concatenating the function name with the route path. The result, after the SDK generators apply their casing, is verbose:

```python
# Python
from geolens.api.datasets import (
    get_single_dataset_datasets_dataset_id_get,
)
```

```typescript
// TypeScript
import { getSingleDatasetDatasetsDatasetIdGet } from '@geolens/sdk';
```

Workaround — import-as aliasing:

```python
from geolens.api.datasets import (
    get_single_dataset_datasets_dataset_id_get as get_dataset,
)
```

```typescript
import {
  getSingleDatasetDatasetsDatasetIdGet as getDataset,
} from '@geolens/sdk';
```

A future minor task may set FastAPI's `generate_unique_id_function` to produce cleaner names. Tracked separately; not blocking current 1.x releases.

### `attrs` not pydantic

Despite GeoLens's backend using pydantic v2, the **generated Python SDK uses `attrs`-based dataclasses**. This is `openapi-python-client`'s output format; it does not affect runtime behavior or type safety. Use `.from_dict()` and `.to_dict()` for (de)serialization. The pydantic v2 idioms (`model_validate`, `model_dump`) do not exist on the generated models.

### X-API-Key header is not in the OpenAPI snapshot

The backend supports three auth modes (header API key, query-param API key, JWT Bearer), but only the JWT scheme is declared in `backend/openapi.json` `components.securitySchemes`. The hand-written `auth.py` / `auth.ts` wrappers add header-based API-key support; the query-param fallback (`?api_key=<key>`) is not exposed by the SDK (it's intended for browser/embed contexts).

### Optional GET bodies — pass `body=None`

For endpoints that declare an optional list body on a GET route (e.g. `/search/datasets/`), `openapi-python-client@0.28.3` unconditionally sets `_kwargs["json"] = body`, and `httpx` cannot serialize the SDK's `Unset` sentinel. **Pass `body=None` explicitly** at the call site. The round-trip tests in `backend/tests/test_sdks_round_trip.py` follow this pattern.

### ASGITransport is async-only

When wiring the Python SDK against an in-process FastAPI app via `httpx.ASGITransport`, use `asyncio_detailed(...)` rather than `sync_detailed(...)`. `ASGITransport` only implements `handle_async_request`; the sync path raises `AttributeError`. Real HTTP endpoints (the publish path) work with either.

### Node engine versions

| Use | Minimum Node version | Why |
|-----|----------------------|-----|
| Consuming `@geolens/sdk` (runtime) | **18** | Native `fetch` is available |
| Regenerating SDK (`make sdks`) | **22.13** | `@hey-api/openapi-ts` 0.91+ requires it for codegen |

The published SDK declares `"engines": { "node": ">=18" }`. The CI workflow uses Node 22 for codegen.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ImportError: cannot import name 'GeolensClient'` | Stale package version | `pip install --upgrade geolens` |
| `ERR_REQUIRE_ESM` | CommonJS consumer trying to require ESM SDK | Use `import` (ESM) — the SDK does not ship a CJS wrapper for 1.x |
| `make sdks-check` fails locally with version-only diff | Stale local clone | `make openapi && make sdks` to refresh |
| `make sdks` fails with "uvx: command not found" | uv not installed | `brew install uv` (macOS) or see <https://docs.astral.sh/uv/getting-started/> |
| First `npm publish @geolens/sdk` fails with `402 Payment Required` | Missing `--access public` | Use `npm publish --access public` (the workflow already does) |
| `TypeError: Object of type Unset is not JSON serializable` | SDK call passed UNSET to a GET body | Pass `body=None` explicitly (see "Optional GET bodies") |
| Round-trip test fails in CI but passes locally | Generator output drift | `make sdks` locally, commit the diff |

## References

- [openapi-python-client docs](https://github.com/openapi-generators/openapi-python-client)
- [@hey-api/openapi-ts docs](https://heyapi.dev/openapi-ts/get-started.html)
- [GeoLens API reference](https://github.com/geolens-io/geolens) (Swagger UI at `/docs` on any running instance)

---

*SDK regeneration: `make sdks` · Drift gate: `make sdks-check` · Round-trip: `make sdks-test`*
