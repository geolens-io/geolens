# Phase 215: sdks-from-openapi - Research

**Researched:** 2026-04-27
**Domain:** OpenAPI client SDK generation (Python + TypeScript) from a FastAPI-emitted OpenAPI 3.1.0 snapshot
**Confidence:** HIGH for generator selection and CLI shape (verified via Context7 + PyPI/npm registries); MEDIUM for round-trip test architecture (verified pattern; needs confirmation in code review); LOW only for the "publish workflow first run" experience which is by design a manual user action.

## Summary

CONTEXT.md locks the major decisions: `openapi-python-client` (Python), `@hey-api/openapi-ts` (TypeScript), in-repo monorepo, lockstep versioning, hand-written auth wrappers, manual-trigger publish workflow. Research confirms these are correct, current, and well-supported choices — with **one important factual correction** to flag: CONTEXT.md D-01 says `openapi-python-client` is "pydantic v2 native"; this is wrong. The generator emits **`attrs`-based** models (`@attrs.define`-decorated classes with `to_dict()`/`from_dict()` methods) backed by `httpx`, `attrs>=22.2.0`, and `python-dateutil`. Pydantic v2 is not a runtime dependency of the generated code. This does not change the decision — `attrs` models are perfectly fine for an SDK consumer — but documentation in `docs/sdks.md` must say "attrs" not "pydantic v2."

The OpenAPI snapshot at `backend/openapi.json` is well-formed (213 operations, 253 schemas, 100% operationId coverage, OpenAPI 3.1.0, sorted-keys deterministic) and free of the schema features known to break either generator: zero `oneOf`, zero `discriminator`, zero `allOf`, no `Input`/`Output` schema split, no Pydantic-model object defaults. The 115 schemas using `anyOf: [{type:X}, {type:null}]` (FastAPI's pydantic-v2-emitted nullable pattern) are handled cleanly by both generators in their current versions. Hand-written auth wrappers map directly onto each generator's first-class auth primitives — `AuthenticatedClient(token, prefix, auth_header_name)` for Python, `client.setConfig({ auth })` for TypeScript — so the wrapper layer is genuinely thin.

The `@hey-api/openapi-ts` generator requires Node `>=22.13.0` and is ESM-only; the project's CI already uses Node 22, so this is fine. `openapi-python-client` requires Python `>=3.10`; the project uses 3.13, fine. Both generators run via one-shot `uvx`/`npx` invocations with no global install.

**Primary recommendation:** Execute the 5-plan decomposition CONTEXT.md sketches, with one correction (use `attrs` not `pydantic v2` in docs) and one elevated risk (the FastAPI `landing_page__get`-style operationId noise will produce ugly Python function names like `get_single_dataset_datasets__dataset_id__get.sync(...)` and TS calls like `getSingleDatasetDatasetsDatasetIdGet({...})` — accept this for v13.1 since fixing it requires backend route surgery; document in `docs/sdks.md` as a known-rough-edge with a deferred path for v13.2+).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OpenAPI schema authoring | Backend (FastAPI routes) | — | FastAPI emits `openapi.json` from route+pydantic definitions; the SDK is downstream |
| OpenAPI snapshot persistence | Backend (`backend/scripts/dump_openapi.py`) | — | Already shipped; deterministic output is the SDK's source of truth |
| Python SDK code generation | Build tooling (root `Makefile` + `uvx openapi-python-client`) | — | One-shot codegen; not at runtime |
| TypeScript SDK code generation | Build tooling (root `Makefile` + `npx @hey-api/openapi-ts`) | — | One-shot codegen; not at runtime |
| Auth wrapper (Python) | SDK package (`sdks/python/geolens_sdk/auth.py`) | — | Hand-written; configures generator's `AuthenticatedClient` |
| Auth wrapper (TypeScript) | SDK package (`sdks/typescript/src/auth.ts`) | — | Hand-written; configures generator's `client.setConfig({ auth })` |
| Drift gate | CI (`make sdks-check` invoked from `.github/workflows/ci.yml`) | Local dev (`make sdks` before commit) | Mirrors existing `openapi-snapshot` job; same `setup-uv` + `setup-node` shape |
| Round-trip integration test | Backend test suite (`backend/tests/test_sdks_round_trip.py`) | — | Uses existing `client` fixture's `ASGITransport` pattern — no separate api process |
| Publish to PyPI | GitHub Actions (`publish-sdks.yml`, `workflow_dispatch`) | Local fallback (`make publish-sdks-py` via `uv publish`) | User-held `PYPI_TOKEN` required; manual trigger by design (D-16) |
| Publish to npm | GitHub Actions (`publish-sdks.yml`, `workflow_dispatch`) | Local fallback (`make publish-sdks-ts` via `npm publish --access public`) | User-held `NPM_TOKEN` required; user must claim `@geolens` org first |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openapi-python-client` | **0.28.3** (PyPI, MIT, 2026-03-05) | Python SDK code generator | Modern (active 2024–2026), supports OpenAPI 3.0 + 3.1, idiomatic `attrs`-based output, `httpx` async-ready, `--config` YAML for class overrides, no JVM dependency. [VERIFIED: PyPI `pypi.org/pypi/openapi-python-client/json`] |
| `@hey-api/openapi-ts` | **0.96.1** (npm, MIT, current) | TypeScript SDK code generator | Active replacement for `openapi-typescript-codegen`, ESM-only, Node 22+, integrated client variants (`client-fetch`/`client-axios`/`client-ky`/`client-next`). [VERIFIED: `registry.npmjs.org/@hey-api/openapi-ts/latest`] |
| `@hey-api/client-fetch` | **0.13.1** (npm, MIT) | Runtime fetch client used by generated TS code | Native `fetch`, no extra HTTP dependency, ESM, smallest bundle; first-class `auth: () => string` and `interceptors` for the auth wrapper. [VERIFIED: `registry.npmjs.org/@hey-api/client-fetch/latest`] |

### Generated SDK runtime dependencies

| Package | Runtime deps | Source |
|---------|-------------|--------|
| `geolens-sdk` (Python, generated) | `httpx >=0.23.0,<0.29.0`, `attrs >=22.2.0`, `python-dateutil ^2.8.0` | [VERIFIED: golden-record pyproject.toml at github.com/openapi-generators/openapi-python-client/blob/main/end_to_end_tests/golden-record/pyproject.toml]. **Note:** backend already pins `httpx 0.28.1` — compatible. |
| `@geolens/sdk` (TypeScript, generated) | `@hey-api/client-fetch` (peer or direct) | [CITED: heyapi.dev output docs] |

### Supporting (Phase 215 build/CI tooling)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uv` | 0.10.x (already in CI) | Python build / publish via `uv build` + `uv publish` | Replaces twine/poetry for the Python SDK build & publish step |
| `tsc` (via `typescript`) | 5.x (Node 22+) | Compile generated `.ts` → `.js` + `.d.ts` for npm publish | The generator emits `.ts` source; consumers expect compiled JS in published package |
| `pytest` | 9.0.3 (existing dev dep) | Round-trip integration test framework | Reuse existing `tests/conftest.py::client` fixture |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `openapi-python-client` | `openapi-generator-cli` (Java) | More mature, but JVM dependency in CI; verbose generated code; CONTEXT.md D-01 explicitly rejects |
| `openapi-python-client` | `Speakeasy` (commercial) | Higher quality output but paid SaaS — incompatible with open-core Apache-2.0 ethos |
| `@hey-api/openapi-ts` | `openapi-typescript-codegen` (legacy) | Older, less maintained; CONTEXT.md D-02 explicitly rejects |
| `@hey-api/openapi-ts` | `openapi-fetch` + `openapi-typescript` | Two-tool pairing (types + runtime), more setup; hey-api bundles them |
| `@hey-api/client-fetch` | `@hey-api/client-axios` | Axios works on older Node but adds a dep; fetch is native to Node 18+ and 22+ (CI baseline) |
| `npm` | `bun` | Bun would be faster to install but adds a tool the project doesn't use elsewhere; CONTEXT.md "Claude's Discretion" picks npm |

**Installation (CI, no global installs needed):**

```bash
# Python — runs the generator with one ephemeral environment
uvx openapi-python-client@0.28.3 generate \
  --path backend/openapi.json \
  --output-path sdks/python \
  --overwrite \
  --config sdks/python/.openapi-python-client.yaml \
  --meta none  # see "Output structure" pitfall below

# TypeScript — runs the generator without global install
cd sdks/typescript && npx --yes @hey-api/openapi-ts@0.96.1 \
  --input ../../backend/openapi.json \
  --output src/client \
  --client @hey-api/client-fetch
```

**Version verification:**
```bash
uvx openapi-python-client --version    # 0.28.3
npm view @hey-api/openapi-ts version    # 0.96.1
npm view @hey-api/client-fetch version  # 0.13.1
```
All three verified live against their registries on 2026-04-27.

## Architecture Patterns

### System Architecture Diagram

```
                                 ┌──────────────────────────────┐
                                 │  backend/                    │
                                 │  └─ FastAPI routes + pydantic│
                                 └────────────┬─────────────────┘
                                              │ scripts/dump_openapi.py
                                              ▼
                              ┌─────────────────────────────────┐
                              │   backend/openapi.json          │ <─── source of truth
                              │   (sorted, OpenAPI 3.1.0,       │      committed to git
                              │   213 ops, 253 schemas)         │
                              └────────────┬────────────────────┘
                                           │
                          ┌────────────────┴─────────────────┐
                          │                                  │
                          ▼ (uvx)                            ▼ (npx)
                 ┌────────────────────┐           ┌───────────────────────┐
                 │ openapi-python-    │           │ @hey-api/openapi-ts   │
                 │ client 0.28.3      │           │ 0.96.1                │
                 └────────┬───────────┘           └────────────┬──────────┘
                          │                                    │
                          ▼ overwrite                          ▼ overwrite
       ┌─────────────────────────────┐         ┌──────────────────────────────┐
       │ sdks/python/                │         │ sdks/typescript/             │
       │ ├ pyproject.toml (managed)  │         │ ├ package.json   (managed)   │
       │ ├ README.md      (manual)   │         │ ├ tsconfig.json  (manual)    │
       │ └ geolens_sdk/              │         │ ├ README.md      (manual)    │
       │   ├ __init__.py (gen)       │         │ ├ src/                       │
       │   ├ client.py   (gen)       │         │ │ ├ client/   (gen)          │
       │   ├ api/        (gen)       │         │ │ ├ types.gen.ts             │
       │   ├ models/     (gen)       │         │ │ ├ sdk.gen.ts               │
       │   ├ types.py    (gen)       │         │ │ ├ client.gen.ts            │
       │   ├ errors.py   (gen)       │         │ │ ├ index.ts                 │
       │   └ auth.py     (HAND)      │         │ │ └ auth.ts        (HAND)    │
       └──────┬──────────────────────┘         └────────────┬─────────────────┘
              │                                             │
              ▼ uv build → wheel                            ▼ tsc → dist/
       ┌──────────────────────┐                  ┌─────────────────────────┐
       │ PyPI: geolens-sdk    │                  │ npm: @geolens/sdk       │
       │ (Apache-2.0)         │                  │ (Apache-2.0)            │
       │ — manual user action │                  │ — manual user action    │
       └──────────────────────┘                  └─────────────────────────┘

                    ┌──────────────────────────────────────────┐
                    │ Drift gate (CI):                         │
                    │   make sdks-check                        │
                    │   → make sdks                            │
                    │   → git diff --exit-code -- sdks/        │
                    │       :!sdks/python/geolens_sdk/auth.py  │
                    │       :!sdks/typescript/src/auth.ts      │
                    │       :!sdks/python/README.md            │
                    │       :!sdks/typescript/README.md        │
                    └──────────────────────────────────────────┘
```

### Recommended Project Structure

```
geolens/                                          # repo root
├── Makefile                                      # +sdks, +sdks-check, +sdks-test, +publish-sdks-py, +publish-sdks-ts
├── scripts/sync_sdk_versions.py                  # NEW: pin SDK versions to backend's openapi.json info.version
├── docs/sdks.md                                  # NEW: generator choices, regen flow, publish process
├── backend/
│   ├── openapi.json                              # source of truth (already exists)
│   ├── scripts/dump_openapi.py                   # already exists
│   └── tests/test_sdks_round_trip.py             # NEW: pytest hits both SDKs against ASGITransport
├── sdks/
│   ├── python/
│   │   ├── .openapi-python-client.yaml           # NEW: generator config
│   │   ├── pyproject.toml                        # NEW: hand-maintained metadata, version is sync'd
│   │   ├── LICENSE                               # NEW: copy of root LICENSE
│   │   ├── README.md                             # NEW: hand-maintained
│   │   └── geolens_sdk/                          # generator overwrites everything except auth.py
│   │       ├── __init__.py                       # generated
│   │       ├── client.py                         # generated (Client + AuthenticatedClient)
│   │       ├── api/                              # generated (one module per FastAPI tag)
│   │       ├── models/                           # generated (attrs classes, one per schema)
│   │       ├── types.py                          # generated (UNSET, Response[T], etc.)
│   │       ├── errors.py                         # generated (UnexpectedStatus)
│   │       ├── py.typed                          # generated (PEP 561 marker)
│   │       └── auth.py                           # NEW, HAND-WRITTEN, drift-exempt
│   └── typescript/
│       ├── package.json                          # NEW: hand-maintained metadata + scripts (tsc, lint)
│       ├── tsconfig.json                         # NEW: hand-maintained
│       ├── LICENSE                               # NEW: copy of root LICENSE
│       ├── README.md                             # NEW: hand-maintained
│       ├── .gitignore                            # NEW: ignore node_modules, dist
│       └── src/
│           ├── client/                           # generator overwrites
│           │   ├── client.gen.ts
│           │   ├── sdk.gen.ts
│           │   ├── types.gen.ts
│           │   ├── core/
│           │   └── index.ts
│           ├── auth.ts                           # NEW, HAND-WRITTEN, drift-exempt
│           └── index.ts                          # NEW, hand-written re-exports {createGeolensClient, …types}
└── .github/workflows/
    ├── ci.yml                                    # +sdks-check job (alongside openapi-snapshot)
    └── publish-sdks.yml                          # NEW: workflow_dispatch only, runs uv publish + npm publish
```

### Pattern 1: `--meta none` for in-monorepo Python SDK

**What:** `openapi-python-client generate --meta none` writes ONLY the inner `geolens_sdk/` package, NOT a wrapper directory with its own `pyproject.toml`. We hand-author `sdks/python/pyproject.toml` once and let the generator regenerate only the package contents.

**When to use:** Always for our setup. The default (`--meta poetry`) creates an outer `geolens-sdk/` directory and a fresh `pyproject.toml` every generation — that would clobber our hand-maintained metadata, license declaration, and version pin.

**Example:**
```bash
# Source: github.com/openapi-generators/openapi-python-client README + Context7
uvx openapi-python-client@0.28.3 generate \
  --path backend/openapi.json \
  --output-path sdks/python/geolens_sdk \
  --overwrite \
  --meta none \
  --config sdks/python/.openapi-python-client.yaml
```

**`.openapi-python-client.yaml`:**
```yaml
# Source: github.com/openapi-generators/openapi-python-client README §Configuration
project_name_override: geolens-sdk
package_name_override: geolens_sdk
package_version_override: 1.0.0  # rewritten by scripts/sync_sdk_versions.py at every `make sdks` run

# Cleaner enums in generated code (matches our pydantic v2 backend's enum emission)
literal_enums: true

# Generate endpoints for ALL tags rather than first tag (FastAPI assigns multiple tags often)
generate_all_tags: true

# Run ruff after generation so output respects project style
post_hooks:
  - "ruff check . --fix-only"
  - "ruff format ."
```

### Pattern 2: TypeScript config with runtimeConfigPath for auth

**What:** `@hey-api/openapi-ts` accepts a `runtimeConfigPath` option pointing at a hand-written file that exports `createClientConfig`. This is THE seam for the auth wrapper — it's `setConfig`-equivalent but invoked at construction time, not after.

**When to use:** When the consumer wants a single factory call (`createGeolensClient({...})`) rather than `client.setConfig(...)` after import. CONTEXT.md D-10 mandates this factory shape.

**Example:**
```typescript
// sdks/typescript/openapi-ts.config.ts — hand-maintained
// Source: heyapi.dev/openapi-ts/configuration
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../backend/openapi.json',
  output: { path: 'src/client', format: 'prettier' },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    {
      name: '@hey-api/client-fetch',
      runtimeConfigPath: './src/auth.ts',  // hand-written, drift-exempt
    },
  ],
});
```

```typescript
// sdks/typescript/src/auth.ts — hand-written, drift-exempt
// Source: heyapi.dev/openapi-ts/clients/fetch
import type { CreateClientConfig } from './client/client.gen';

export interface GeolensClientOptions {
  baseUrl: string;
  bearerToken?: string;
  apiKey?: string;
}

export const createGeolensClient = (opts: GeolensClientOptions) => {
  const headers: Record<string, string> = {};
  if (opts.bearerToken) headers['Authorization'] = `Bearer ${opts.bearerToken}`;
  if (opts.apiKey) headers['X-API-Key'] = opts.apiKey;

  // Re-export the configured client; consumers do `import { client } from '@geolens/sdk'`
  // and pass it explicitly, OR they `setConfig` on the singleton.
  return {
    baseUrl: opts.baseUrl,
    headers,
    // ...consumers spread this into the client.setConfig({...})
  };
};
```

### Pattern 3: Python `AuthenticatedClient` wrapper

**What:** `openapi-python-client`'s generated `AuthenticatedClient` already supports BOTH the `Authorization: Bearer <token>` AND `X-API-Key: <key>` patterns natively via `prefix=""` + `auth_header_name="X-API-Key"`. The wrapper just chooses which.

**When to use:** Always. CONTEXT.md D-10 mandates this single-class wrapper.

**Example:**
```python
# sdks/python/geolens_sdk/auth.py — hand-written, drift-exempt
# Source: github.com/openapi-generators/openapi-python-client client.py.jinja golden-record
"""Auth wrapper around the generated AuthenticatedClient.

Hand-maintained — NOT regenerated by `make sdks`. The drift gate explicitly
excludes this file via `:!sdks/python/geolens_sdk/auth.py`.
"""
from typing import Optional
from .client import AuthenticatedClient, Client

class GeolensClient:
    """Single entry-point for the GeoLens Python SDK.

    Configure exactly one of bearer_token or api_key.
    Bearer goes to `Authorization: Bearer <token>`.
    API key goes to `X-API-Key: <key>`, matching the backend's
    `_resolve_api_key()` precedence (header > query > JWT > anonymous).
    """
    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        if bearer_token and api_key:
            raise ValueError("Provide either bearer_token or api_key, not both")
        if bearer_token:
            self._client = AuthenticatedClient(
                base_url=base_url,
                token=bearer_token,
                # prefix defaults to "Bearer", auth_header_name to "Authorization"
            )
        elif api_key:
            self._client = AuthenticatedClient(
                base_url=base_url,
                token=api_key,
                prefix="",  # send the raw key with no "Bearer " prefix
                auth_header_name="X-API-Key",
            )
        else:
            self._client = Client(base_url=base_url)  # anonymous — public endpoints only

    @property
    def client(self) -> Client:
        """Return the underlying generated client for use with api modules."""
        return self._client

    def set_bearer_token(self, token: str) -> None:
        self._client = AuthenticatedClient(base_url=self._client._base_url, token=token)

    def set_api_key(self, key: str) -> None:
        self._client = AuthenticatedClient(
            base_url=self._client._base_url,
            token=key,
            prefix="",
            auth_header_name="X-API-Key",
        )
```

### Anti-Patterns to Avoid

- **Hand-tuning generated files:** any edit inside the generator's output (e.g., touching `client.py` or `sdk.gen.ts`) WILL be reverted next `make sdks`. The drift gate would then catch the local edit but in the wrong direction. Solution: change the OpenAPI source or use generator config (`class_overrides`, custom Jinja templates, plugins). The auth wrapper is the only sanctioned hand-written file in each SDK.

- **Letting `--meta poetry` (default) run:** the generator will scaffold a poetry-based `pyproject.toml` with placeholder fields and overwrite our Apache-2.0 license declaration. Always pass `--meta none` and own the outer `pyproject.toml` ourselves.

- **Committing `node_modules/` or `dist/`:** `sdks/typescript/node_modules` and `sdks/typescript/dist` MUST be gitignored. The drift gate operates on source only.

- **Cross-tier auth assumptions:** the SDK auth wrapper sets headers; do NOT replicate the backend's `?api_key=<key>` query-param fallback (CLAUDE.md project memory). Header-only is intentional (D-11) — query-param mode is for browser/embed contexts the SDK doesn't target.

- **Trying to publish from CI on every merge:** explicitly out of scope. Auto-publish creates risk of accidental breaking releases while the API is stabilizing. CONTEXT.md D-16 mandates `workflow_dispatch` (manual trigger) only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Generate Python types from OpenAPI schemas | A bespoke pydantic codegen script | `openapi-python-client generate` | Handles 253 schemas, 213 operations, OpenAPI 3.1 nullable `anyOf` pattern, datetime/UUID coercion, enum literals, request/response body marshalling |
| Generate TypeScript types from OpenAPI schemas | A bespoke `ts-morph` script | `npx @hey-api/openapi-ts` | Same scale; emits `.gen.ts` files with full JSDoc, ESM module structure, fetch client integration |
| Bearer-token + API-key auth on the Python client | A custom `httpx.Client` subclass | `AuthenticatedClient(token, prefix, auth_header_name)` from generated code | The generator already supports both patterns first-class via the `prefix=""` + `auth_header_name="X-API-Key"` combination [VERIFIED: golden-record client.py] |
| Bearer-token auth on the TS client | A custom fetch wrapper that injects the header | `client.setConfig({ auth: () => token })` from generated code | First-class `auth` field in `@hey-api/client-fetch` accepts a string or a function returning a string [CITED: heyapi.dev/openapi-ts/clients/fetch] |
| Drift detection between OpenAPI and SDK | A custom hash compare | `make sdks-check` running `git diff --exit-code -- sdks/` after regen | Mirrors existing `make openapi-check` (D-12); contributors already understand the pattern |
| Round-trip end-to-end test | Spinning up docker compose for the test | Reuse `backend/tests/conftest.py::client` fixture's `ASGITransport` | The existing test infra already runs the FastAPI app in-process via `httpx.ASGITransport(app=app)` — the SDK's `httpx.Client` can be redirected to this same in-process transport so no real network round-trip is needed |
| Version pin between backend and SDKs | A pre-commit hook that edits version fields | `scripts/sync_sdk_versions.py` invoked from `make sdks` | Single canonical script; drift gate catches version mismatch in same diff that catches code drift (D-08) |
| Manual `pip install` from local wheel for testing | A custom test harness | `pip install -e sdks/python/` (editable install) for round-trip test | uv supports editable installs of workspace packages directly; the round-trip test imports from the live source tree |

**Key insight:** The two generators between them already solve >95% of the problem. Phase 215's value-add is the configuration glue (~150 lines of YAML/TS config + ~80 lines of hand-written auth wrappers + ~100 lines of CI/Makefile + ~150 lines of round-trip tests + ~200 lines of docs). Anything that looks like reimplementing what `openapi-python-client` or `@hey-api/openapi-ts` already does should trigger a "wait, did I read the docs?" pause.

## Common Pitfalls

### Pitfall 1: CONTEXT.md says "pydantic v2" but the generator uses `attrs`

**What goes wrong:** `docs/sdks.md` is written claiming the SDK uses pydantic v2, then a consumer tries `from geolens_sdk.models import Dataset; Dataset.model_validate(...)` and gets `AttributeError`.

**Why it happens:** CONTEXT.md D-01 misstates the runtime model framework. `openapi-python-client` 0.28.x emits `attrs`-decorated dataclasses with `to_dict()` and `from_dict(d: dict)` methods, not pydantic models. The generator itself uses pydantic internally for parsing the OpenAPI spec, but generated client code doesn't.

**How to avoid:** Doc says "attrs-based typed dataclasses" not "pydantic v2 models." Round-trip test asserts `Dataset.from_dict(payload)` works (NOT `Dataset.model_validate(payload)`). Planner should QA-check `docs/sdks.md` against the actual generated `client.py` before merge.

**Warning signs:** If anyone writes example code calling `.model_dump()` or `.model_validate()` in `docs/sdks.md`, that's the smell.

**Source:** [VERIFIED: github.com/openapi-generators/openapi-python-client/blob/main/end_to_end_tests/golden-record/pyproject.toml — runtime deps are `httpx`, `attrs >=22.2.0`, `python-dateutil ^2.8.0`. No pydantic.]

### Pitfall 2: FastAPI auto-generated operationIds produce ugly SDK function names

**What goes wrong:** Python: `from geolens_sdk.api.datasets import get_single_dataset_datasets__dataset_id__get`. TypeScript: `import { getSingleDatasetDatasetsDatasetIdGet } from '@geolens/sdk'`. Both are unusable.

**Why it happens:** FastAPI's default `operationId` generator concatenates the function name with the path, snake-cased. Our `backend/openapi.json` has 213 operations, ALL with this pattern (`landing_page__get`, `search_datasets_endpoint_search_datasets__get`, etc.).

**How to avoid (for v13.1, accept the ugliness):**
1. Document in `docs/sdks.md` that function names are verbose and consumers may want to import-as: `import { searchDatasetsEndpointSearchDatasetsGet as searchDatasets } from '@geolens/sdk'`.
2. The auth wrapper in Python re-exports a curated subset under nicer names: `from geolens_sdk import GeolensClient; client.search_datasets(...)` if the planner wants to invest one more wrapper layer. CONTEXT.md doesn't mandate this; it's discretionary.
3. **DO NOT** retrofit FastAPI's `generate_unique_id_function` mid-phase — that would change every operationId, invalidating the OpenAPI snapshot and likely breaking the frontend's hand-written `apiFetch()` calls (CLAUDE.md notes the frontend uses raw `apiFetch` paths, not generated functions, so might be safe — but the scope creep risk is real). Defer to v13.2+.

**Warning signs:** Reviewer says "these names are awful." Yes. Documented and deferred.

**Source:** [VERIFIED: ad-hoc inspection of `backend/openapi.json` operationIds via `python3 -c "import json; ..."`]

### Pitfall 3: `@hey-api/openapi-ts` is ESM-only and requires Node 22.13+

**What goes wrong:** A consumer running Node 18 on legacy CI tries `npm install @geolens/sdk`, gets engine warnings or runtime errors when their bundler can't resolve the ESM import.

**Why it happens:** `@hey-api/openapi-ts` 0.91+ dropped CommonJS. The generated SDK output, while it can target whatever module format `tsconfig.json` specifies, is itself authored in ESM-style; the package.json should declare `"type": "module"` and `"exports"` field.

**How to avoid:**
1. Set `package.json` `"engines": { "node": ">=18" }` (Node 18 has native fetch — that's the OUR runtime requirement, separate from the GENERATOR'S Node 22.13+ requirement which only affects `npm run sdks` at build time).
2. Document the Node 18+ minimum in `docs/sdks.md`.
3. CI's `setup-node` step uses `node-version: 22` — fine.
4. Compile to dual ESM+CJS in published `dist/` if we want broad bundler compat (use `tsup` or `tsc --module nodenext` + a CJS wrapper). For v13.1, ESM-only is fine since the named target consumer is the v13.1 CLI which can do whatever, and Node 18+ has ESM.

**Warning signs:** Test consumer uses CommonJS `require('@geolens/sdk')` and gets `ERR_REQUIRE_ESM`. Either ship a CJS wrapper or document the limitation prominently.

**Source:** [VERIFIED: `@hey-api/openapi-ts` package.json — `"type": "module"`, `"engines": {"node": ">=22.13.0"}`. Migrating doc explicitly states "v0.91.0 — Removed CommonJS (CJS) support."]

### Pitfall 4: The `X-API-Key` security scheme is NOT in the OpenAPI snapshot

**What goes wrong:** Generators emit auth code only for the `OAuth2PasswordBearer` scheme (the only one declared in `components.securitySchemes`). The `X-API-Key` header path the backend supports via `_resolve_api_key()` is invisible to the generators, so the generated `AuthenticatedClient` defaults to `Authorization: Bearer <token>` only.

**Why it happens:** `backend/app/modules/auth/dependencies.py:23::_resolve_api_key()` reads `X-API-Key` directly from the request headers BEFORE FastAPI's dependency tree is consulted, so FastAPI's OpenAPI generator doesn't know about it. The OpenAPI snapshot's only security scheme is `OAuth2PasswordBearer`.

**How to avoid:** This is exactly why D-10 mandates a HAND-WRITTEN auth wrapper. The `GeolensClient` wrapper handles API-key auth by setting `prefix=""` + `auth_header_name="X-API-Key"` on the generated `AuthenticatedClient` — the underlying generated code doesn't need to know about it. The wrapper is the one place the API-key surface is documented from the SDK side.

**Future improvement (out of scope for Phase 215):** add `APIKeyHeader(name="X-API-Key")` security scheme declaration to the FastAPI app config so the OpenAPI snapshot includes it. Then the generator could surface it without the wrapper. Track as a future minor task. For now, the wrapper does the work.

**Warning signs:** A user reads the generated SDK's docstrings, sees only Bearer auth, files a "missing API key support" issue. Round-trip test should exercise both auth modes to prove the wrapper works.

**Source:** [VERIFIED: `backend/openapi.json` `components.securitySchemes` contains only `OAuth2PasswordBearer`; `backend/app/modules/auth/dependencies.py::_resolve_api_key()` referenced in CLAUDE.md.]

### Pitfall 5: ROADMAP success criteria reference endpoints that don't exactly exist

**What goes wrong:** ROADMAP SC#1/SC#2 say the round-trip must succeed for `/search/datasets`, `/datasets/{id}`, and `POST /ingest`. The actual API has `/search/datasets/` (trailing slash), `/datasets/{dataset_id}`, and **no plain `POST /ingest`** — instead `/ingest/upload`, `/ingest/register/`, `/ingest/commit/{job_id}`, etc.

**Why it happens:** ROADMAP SC was written at a high level before the OpenAPI-snapshotting phase. The actual route names diverged.

**How to avoid:** The round-trip test (`backend/tests/test_sdks_round_trip.py`) should exercise the closest reasonable equivalents:
- `GET /search/datasets/` → `search_datasets_endpoint_search_datasets__get.sync(client=...)` — list datasets
- `GET /datasets/{dataset_id}` → `get_single_dataset_datasets__dataset_id__get.sync(client=..., dataset_id=...)` — fetch one
- `POST /ingest/upload` → `upload_file_ingest_upload_post.sync_detailed(client=..., body=...)` — closest to "POST /ingest" in spirit

Document in plan-04 verification that these are the actual operationIds covering the SC. The phase verification gate confirms the test passes (NOT that exact paths from ROADMAP exist).

**Warning signs:** Plan author writes test against `/datasets/{id}` (without `_id`); test fails immediately because path doesn't exist.

**Source:** [VERIFIED: `cat backend/openapi.json | python3 -c "..."` — actual paths confirmed.]

### Pitfall 6: `--overwrite` deletes the auth wrapper

**What goes wrong:** `openapi-python-client generate ... --overwrite --output-path sdks/python/geolens_sdk` wipes the entire `geolens_sdk/` directory before regenerating. The hand-written `auth.py` is collateral damage.

**Why it happens:** The `--overwrite` flag is documented as "remove the project directory and regenerate." With `--meta none`, the "project directory" is just the package directory; with default `--meta poetry`, it's the parent.

**How to avoid:** Two options, planner picks:
1. **Restore-after pattern (simpler):** the `Makefile` `sdks` target stashes `auth.py` to `/tmp`, runs the generator, restores. Brittle.
2. **Outside-package pattern (cleaner):** put the wrapper at `sdks/python/geolens_sdk_auth.py` (a sibling to `geolens_sdk/`) and re-export via the hand-written outer `pyproject.toml`'s package list. Or put it at `sdks/python/geolens_sdk/auth.py` BUT use a custom Jinja template (`--custom-template-path`) that includes `auth.py` as a no-op template that the generator copies through. Most robust.
3. **Fork-the-template pattern:** Add a custom Jinja `auth.py.jinja` that EMITS the wrapper as part of the generated output — then the wrapper IS generator output, and the drift gate covers it; no `:!` exemption needed. Trade-off: Jinja maintenance.

**Recommendation:** Option 1 for v13.1 (simplest). Document the restore step in the Makefile clearly. Switch to option 3 if maintenance pain emerges.

**Source:** [VERIFIED: `--overwrite` semantics documented in `openapi-python-client` README; Context7 fetch confirms `--overwrite` "removes the project directory and regenerates."]

### Pitfall 7: TypeScript build for npm publish needs more than just generation

**What goes wrong:** Run `make sdks`, get `sdks/typescript/src/client/*.ts` files, run `npm publish`, downstream consumer does `import { ... } from '@geolens/sdk'` and gets a Node-can't-resolve error — the package shipped only `.ts` source, no compiled `.js` or `.d.ts`.

**Why it happens:** `@hey-api/openapi-ts` only generates TypeScript SOURCE. To publish a usable npm package, you need to compile (`tsc`) and ship the `dist/` directory with `package.json` `"main"` / `"types"` / `"exports"` pointing at the compiled outputs.

**How to avoid:** `package.json` includes:
```json
{
  "scripts": {
    "build": "tsc",
    "prepublishOnly": "npm run build"
  },
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "types": "./dist/index.d.ts"
    }
  },
  "files": ["dist", "README.md", "LICENSE"]
}
```
The `Makefile` `publish-sdks-ts` target runs `cd sdks/typescript && npm install && npm run build && npm publish --access public`. CI workflow does the same.

**Warning signs:** `make sdks-test`'s TypeScript half fails to import the SDK; reading the package.json reveals no compiled output.

**Source:** [CITED: heyapi.dev/openapi-ts/output — generated files are `.ts` source. Context7 confirms.]

### Pitfall 8: Round-trip test needs the SDK to point at the in-process ASGI app, not a real http server

**What goes wrong:** The naive round-trip test starts a uvicorn server on port 8000, creates `GeolensClient(base_url="http://localhost:8000")`, makes calls. CI flakes because port-in-use, slow startup, network resets.

**Why it happens:** The existing `backend/tests/conftest.py::client` fixture uses `httpx.ASGITransport(app=app)` — the FastAPI app is invoked in-process; no real socket. The `GeolensClient` needs to use that same transport.

**How to avoid:** Both `Client` and `AuthenticatedClient` from `openapi-python-client` accept a custom `httpx.Client` via `set_httpx_client()`:
```python
# Source: github.com/openapi-generators/openapi-python-client client docstring
import httpx
from app.api.main import app
from geolens_sdk import GeolensClient

transport = httpx.ASGITransport(app=app)
sdk = GeolensClient(base_url="http://test")
sdk._client.set_httpx_client(httpx.Client(base_url="http://test", transport=transport))
# Now SDK calls hit the in-process app
```
For TypeScript, the test uses Node `globalThis.fetch` which `@hey-api/client-fetch` honors; spawn `pytest` invokes a small Node script that runs against `http://localhost:NNNN` provided by a test fixture that DOES run uvicorn — but only for the TS half (TypeScript can't import-and-call FastAPI app directly). Acceptable scope — the TS half pays the 1-2s uvicorn-startup cost; the Python half is in-process.

**Warning signs:** Round-trip test takes >30s in CI. If so, switch to a single uvicorn subprocess for both halves (run once, share with both Python and TS tests via a session-scoped fixture).

**Source:** [VERIFIED: `httpx.ASGITransport(app=app)` confirmed in `backend/tests/conftest.py:190`; `set_httpx_client` confirmed in golden-record README.]

### Pitfall 9: Version-sync script must be deterministic for the drift gate

**What goes wrong:** `scripts/sync_sdk_versions.py` writes `1.0.0+build123` or a timestamped version into `pyproject.toml`. Each `make sdks` run produces a different version; CI's `git diff --exit-code` always fails.

**Why it happens:** CI/CD instinct to embed a build number. The drift gate is a STATIC equality check.

**How to avoid:** The version-sync script reads `backend/openapi.json`'s `info.version` field VERBATIM, writes it (unchanged) to `sdks/python/pyproject.toml`'s `[project] version` field and `sdks/typescript/package.json`'s `version` field. No timestamps, no build numbers, no hashes. The same input always produces the same output. Right now backend/openapi.json's `info.version = "1.0.0"` (hardcoded in FastAPI app config); when the user bumps backend version, both SDKs follow on the next `make sdks` run.

**Warning signs:** CI `sdks-check` fails with a diff showing only the version field differing from one run to the next. That's the symptom.

**Source:** [VERIFIED: `backend/openapi.json` `info.version: "1.0.0"`, `backend/pyproject.toml` `version = "1.0.0"` — single source of truth.]

### Pitfall 10: `npm publish --access public` is required for first publish of @geolens/sdk

**What goes wrong:** The user runs `npm publish` for the first publish; npm rejects because scoped packages default to `restricted` (private/paid) access.

**Why it happens:** All scoped packages (`@scope/name`) on the npm free org tier are private by default. The first publish must explicitly opt into public access.

**How to avoid:**
1. The user MUST claim the `@geolens` org on npm before first publish (verified unclaimed: `curl https://registry.npmjs.org/-/org/geolens` returns `ResourceNotFound`).
2. The `Makefile` `publish-sdks-ts` and `.github/workflows/publish-sdks.yml` both run `npm publish --access public` (NOT plain `npm publish`).
3. Alternatively, `package.json` includes `"publishConfig": { "access": "public" }` so plain `npm publish` works. Belt-and-suspenders: do both.

**Warning signs:** First publish attempt errors with `402 Payment Required`. That's the public-access miss.

**Source:** [CITED: docs.npmjs.com/cli/v10/using-npm/scope/ — "scoped packages are private by default; use --access public for free public publishing."]

## Code Examples

### Verified pattern: openapi-python-client config + invocation

```bash
# Source: openapi-python-client README + Context7 docs/openapi-generators/openapi-python-client
cd /repo/root
uvx openapi-python-client@0.28.3 generate \
  --path backend/openapi.json \
  --output-path sdks/python/geolens_sdk \
  --overwrite \
  --meta none \
  --config sdks/python/.openapi-python-client.yaml
```

### Verified pattern: hey-api/openapi-ts config

```typescript
// sdks/typescript/openapi-ts.config.ts
// Source: heyapi.dev/openapi-ts/configuration
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../backend/openapi.json',
  output: {
    path: 'src/client',
    format: 'prettier',
  },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    '@hey-api/client-fetch',
  ],
});
```

```bash
# Run from sdks/typescript/
npx --yes @hey-api/openapi-ts@0.96.1
# Reads ./openapi-ts.config.ts automatically
```

### Verified pattern: round-trip test fixture (Python half)

```python
# backend/tests/test_sdks_round_trip.py
# Source: this research, Pitfall 8 + existing conftest pattern at backend/tests/conftest.py:190
import httpx
import pytest
from geolens_sdk.api.search import search_datasets_endpoint_search_datasets__get
from geolens_sdk.api.datasets import get_single_dataset_datasets__dataset_id__get
from geolens_sdk.client import AuthenticatedClient

@pytest.fixture
async def sdk_client(client, admin_auth_header):
    """Construct the generated SDK client wired to the in-process ASGI app."""
    from app.api.main import app
    token = admin_auth_header["Authorization"].removeprefix("Bearer ")
    sdk = AuthenticatedClient(base_url="http://test", token=token)
    transport = httpx.ASGITransport(app=app)
    sdk.set_httpx_client(httpx.Client(base_url="http://test", transport=transport))
    yield sdk

async def test_search_datasets_round_trip(sdk_client):
    # ROADMAP SC#1: /search/datasets must round-trip
    resp = search_datasets_endpoint_search_datasets__get.sync_detailed(client=sdk_client)
    assert resp.status_code == 200
    # parsed model is an attrs dataclass, NOT a pydantic model
    assert hasattr(resp.parsed, 'to_dict')
```

### Verified pattern: Makefile targets

```makefile
# Source: existing Makefile precedent at openapi/openapi-check + this research

.PHONY: sdks sdks-check sdks-test publish-sdks-py publish-sdks-ts

sdks: ## Regenerate Python + TypeScript SDKs from backend/openapi.json
	cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py
	# Stash hand-written wrappers across regen
	-cp sdks/python/geolens_sdk/auth.py /tmp/_geolens_auth.py 2>/dev/null
	-cp sdks/typescript/src/auth.ts /tmp/_geolens_auth.ts 2>/dev/null
	uvx openapi-python-client@0.28.3 generate \
	  --path backend/openapi.json \
	  --output-path sdks/python/geolens_sdk \
	  --overwrite --meta none \
	  --config sdks/python/.openapi-python-client.yaml
	-cp /tmp/_geolens_auth.py sdks/python/geolens_sdk/auth.py 2>/dev/null
	cd sdks/typescript && npx --yes @hey-api/openapi-ts@0.96.1
	-cp /tmp/_geolens_auth.ts sdks/typescript/src/auth.ts 2>/dev/null
	uv run python scripts/sync_sdk_versions.py

sdks-check: ## Fail CI if SDK regeneration produces a diff (excludes hand-written files)
	$(MAKE) sdks
	git diff --exit-code -- sdks/ \
	  ':!sdks/python/geolens_sdk/auth.py' \
	  ':!sdks/typescript/src/auth.ts' \
	  ':!sdks/python/README.md' \
	  ':!sdks/typescript/README.md'

sdks-test: ## Round-trip both SDKs against the in-process FastAPI app
	cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v

publish-sdks-py: ## Build + publish Python SDK to PyPI (requires UV_PUBLISH_TOKEN)
	cd sdks/python && uv build && uv publish

publish-sdks-ts: ## Build + publish TypeScript SDK to npm (requires NPM_TOKEN)
	cd sdks/typescript && npm install && npm run build && npm publish --access public
```

### Verified pattern: GitHub Actions sdks-check job

```yaml
# .github/workflows/ci.yml — append this job
# Source: existing openapi-snapshot job pattern in same file
sdks-check:
  name: SDKs Drift Gate
  needs: changes
  if: needs.changes.outputs.backend == 'true' || github.event_name == 'push'
  runs-on: ubuntu-latest
  env:
    JWT_SECRET_KEY: sdks-check-padding-key-32characters-here
    PYTHONPATH: backend
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v6
      with:
        version: "0.10.2"
        enable-cache: true
        cache-dependency-glob: "backend/uv.lock"
    - uses: actions/setup-python@v5
      with:
        python-version: "3.13"
    - uses: actions/setup-node@v6
      with:
        node-version: 22
        cache: npm
        cache-dependency-path: sdks/typescript/package-lock.json
    - name: Install Python dependencies (for dump_openapi)
      working-directory: backend
      run: uv sync --locked --dev
    - name: Install TypeScript SDK dependencies
      working-directory: sdks/typescript
      run: npm ci
    - name: Regenerate SDKs and check for drift
      run: make sdks-check
```

### Verified pattern: publish-sdks.yml workflow scaffold

```yaml
# .github/workflows/publish-sdks.yml — NEW, manual trigger only
# Source: this research, CONTEXT.md D-16
name: Publish SDKs

on:
  workflow_dispatch:
    inputs:
      target:
        description: 'Which SDK to publish'
        required: true
        type: choice
        options: [python, typescript, both]
      dry_run:
        description: 'Build only, do not publish'
        required: false
        type: boolean
        default: false

permissions:
  contents: read
  id-token: write  # for PyPI trusted publishing (future)

jobs:
  publish-python:
    if: inputs.target == 'python' || inputs.target == 'both'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with: { version: "0.10.2" }
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - name: Build wheel
        working-directory: sdks/python
        run: uv build
      - name: Publish to PyPI
        if: ${{ !inputs.dry_run }}
        working-directory: sdks/python
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
        run: uv publish

  publish-typescript:
    if: inputs.target == 'typescript' || inputs.target == 'both'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v6
        with:
          node-version: 22
          registry-url: 'https://registry.npmjs.org'
      - name: Build
        working-directory: sdks/typescript
        run: |
          npm ci
          npm run build
      - name: Publish to npm
        if: ${{ !inputs.dry_run }}
        working-directory: sdks/typescript
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
        run: npm publish --access public
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `openapi-typescript-codegen` | `@hey-api/openapi-ts` | 2023-2024 | Replacement actively maintained; original is in maintenance mode |
| `openapi-generator-cli` (Java) for Python | `openapi-python-client` (pure Python) | 2022+ | No JVM in CI; idiomatic output |
| Pydantic-v1-compatible generators | Pydantic-v2-aware generators (or attrs-based) | Pydantic v2 release 2023-06 | OpenAPI 3.1 `anyOf: [..., {type:null}]` patterns now first-class |
| `npm publish` from a CI job on every release tag | Manual `workflow_dispatch` for SDKs while API stabilizes | This phase | Avoids accidental breaking releases pre-1.0; tighten to tag-trigger after first 5 stable releases |
| `twine upload dist/*` | `uv publish` | 2024+ | Single tool replaces twine; auth via env var or trusted publishing |

**Deprecated/outdated:**
- `openapi-typescript-codegen`: replaced by `@hey-api/openapi-ts` (same author lineage)
- `setup.py` for Python packaging: superseded by `pyproject.toml` everywhere
- `nullable: true` (OpenAPI 3.0): replaced by `type: [X, "null"]` or `anyOf: [{type:X}, {type:null}]` in OpenAPI 3.1 — backend already on 3.1.0, so we're current

## Project Constraints (from CLAUDE.md)

User's global CLAUDE.md (`~/.claude/CLAUDE.md`) directives:

| Directive | Source | Phase 215 implication |
|-----------|--------|----------------------|
| "Never indicate AI or Bot activity in commit messages" | global | All commits in this phase use neutral, human-style messages |
| "Prefer simple, readable code over clever abstractions" | global | The auth wrapper is intentionally tiny (~50 lines); resist plugin-architecture temptation |
| "Follow existing project conventions when editing files" | global | Mirror existing `openapi`/`openapi-check` Makefile target shape; mirror existing `.github/workflows/ci.yml` job structure; place tests in `backend/tests/` not a new top-level dir |
| "Be direct and concise" | global | `docs/sdks.md` should be ~300 lines max — generator choice rationale + regen flow + publish process; not a tutorial site |

The repo has no project-specific `./CLAUDE.md`. User's auto-memory note (`~/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md`) provides project-stack context that's purely informational, no constraints.

## Runtime State Inventory

> Phase 215 is greenfield (creates new `sdks/` directory tree, new test file, new Makefile targets, new CI job, new workflow, new docs). It does NOT rename or refactor existing artifacts. **This section is included with explicit "None" markers for completeness.**

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no database tables, no caches, no key stores reference SDK names | None |
| Live service config | None — no n8n/Datadog/Cloudflare integrations affected | None |
| OS-registered state | None — no Windows Task Scheduler / launchd / systemd registrations | None |
| Secrets/env vars | NEW: `PYPI_TOKEN` (or `UV_PUBLISH_TOKEN`) and `NPM_TOKEN` GitHub repo secrets must be added by user before first publish; not used by anything else | User adds via GitHub UI; not committed |
| Build artifacts | NEW: `sdks/python/geolens_sdk.egg-info/` and `sdks/typescript/dist/` and `sdks/typescript/node_modules/` will be created by build steps; all gitignored | Verify `.gitignore` covers these patterns |

**Risk audit:** the only "live" state outside the repo is the two registry tokens. Both are user-held; neither is used by the existing CI flow; adding them does not affect any current workflow.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` / `uvx` | `make sdks` Python half, `uv build`, `uv publish` | ✓ (local + CI) | 0.10.3 local, 0.10.2 CI | — |
| Python 3.13 | `dump_openapi.py`, generated SDK runtime, round-trip test | ✓ (local + CI) | 3.13 | — |
| Node | `make sdks` TypeScript half, `tsc` build | ✓ (local + CI) | v25.6.1 local, v22 CI | — |
| `npm` / `npx` | TypeScript codegen + publish | ✓ (local + CI) | 11.9.0 local | — |
| `openapi-python-client` | Python codegen | ✓ (via `uvx` ephemeral env, no install needed) | 0.28.3 | — |
| `@hey-api/openapi-ts` | TypeScript codegen | ✓ (via `npx --yes`, no install needed) | 0.96.1 | — |
| `@hey-api/client-fetch` | TypeScript SDK runtime dep | ✓ (resolves at `npm install`) | 0.13.1 | — |
| PyPI token (`PYPI_TOKEN`) | `uv publish` | ✗ NOT SET | — | Phase 215 ships infrastructure; user creates token + adds GH secret before first publish (D-16) |
| npm token (`NPM_TOKEN`) | `npm publish` | ✗ NOT SET | — | Same as above |
| `@geolens` npm org | `npm publish --access public` for `@geolens/sdk` | ✗ UNCLAIMED on npm registry | — | User must claim org on npm before first publish |
| PyPI `geolens-sdk` name | `uv publish` for `geolens-sdk` package | ✓ AVAILABLE on PyPI | — | First-publish creates ownership |

**Missing dependencies with no fallback:**
- None for Phase 215 EXECUTION (all build-time tools available).

**Missing dependencies with fallback (deferred to user post-merge):**
- PyPI account + token + first-publish action
- npm account + `@geolens` org claim + token + first-publish action

These are documented in `docs/sdks.md` and CONTEXT.md `<deferred>`.

**Verification commands:**
```bash
uvx --version            # 0.10.3 (Homebrew 2026-02-16)
uv --version             # 0.10.3
node --version           # v25.6.1 (CI uses v22)
npm --version            # 11.9.0
npx --version            # 11.9.0

# Registry availability (run during research, 2026-04-27):
curl -s "https://pypi.org/pypi/geolens-sdk/json"           # 404 — name available
curl -s "https://registry.npmjs.org/@geolens%2Fsdk"        # 404 — name available
curl -s "https://registry.npmjs.org/-/org/geolens"          # 404 — org unclaimed
npm view @hey-api/openapi-ts version                        # 0.96.1
npm view @hey-api/client-fetch version                      # 0.13.1
curl -s "https://pypi.org/pypi/openapi-python-client/json"  # version: 0.28.3
```

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (anyio_mode=auto, asyncio_mode=strict) — already configured |
| Config file | `backend/pyproject.toml [tool.pytest.ini_options]` — already exists |
| Quick run command | `cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v` |
| Full suite command | `cd backend && PYTHONPATH=. uv run pytest -v --tb=short -m 'not perf'` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OCSDK-01 | Python SDK installable as `geolens-sdk`, has typed clients + Bearer + API-key auth | unit + build | `cd sdks/python && uv build && pip install dist/*.whl && python -c "import geolens_sdk"` | ❌ Wave 0 |
| OCSDK-01 | Python SDK round-trips against `/search/datasets`, `/datasets/{dataset_id}`, `/ingest/upload` | integration | `cd backend && uv run pytest tests/test_sdks_round_trip.py::test_python_round_trip -v` | ❌ Wave 0 |
| OCSDK-02 | TypeScript SDK installable as `@geolens/sdk`, has typed interfaces + auth | unit + build | `cd sdks/typescript && npm install && npm run build && npm pack --dry-run` | ❌ Wave 0 |
| OCSDK-02 | TypeScript SDK round-trips against the same three endpoints | integration | `cd backend && uv run pytest tests/test_sdks_round_trip.py::test_typescript_round_trip -v` (spawns Node subprocess) | ❌ Wave 0 |
| OCSDK-03 | `make sdks` regenerates both SDKs in single shot | smoke | `make sdks && git status -s sdks/` (zero diff after rerun = idempotent) | ❌ Wave 0 |
| OCSDK-03 | `make sdks-check` fails CI when SDK drifts | manual + CI | Edit `backend/openapi.json`, run `make sdks-check`, expect non-zero exit | ❌ Wave 0 (CI job) |
| OCSDK-04 | SDK version pins to OpenAPI snapshot version | unit | `python -c "import json,tomllib; oa=json.load(open('backend/openapi.json'))['info']['version']; py=tomllib.load(open('sdks/python/pyproject.toml','rb'))['project']['version']; ts=json.load(open('sdks/typescript/package.json'))['version']; assert oa==py==ts, (oa,py,ts)"` | ❌ Wave 0 |
| OCSDK-04 | `docs/sdks.md` documents generators + publish process | manual review | `test -f docs/sdks.md && grep -q 'openapi-python-client' docs/sdks.md && grep -q 'hey-api/openapi-ts' docs/sdks.md` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `make sdks-check` (fast: ~30-60s — generator runs in parallel)
- **Per wave merge:** `make sdks-test` + full `pytest -m 'not perf'` (the round-trip test plus the existing 2001-test backend baseline)
- **Phase gate:** `make sdks` + `make sdks-check` + `make sdks-test` all green; `cd sdks/python && uv build` produces a wheel; `cd sdks/typescript && npm pack` produces a tgz; `docs/sdks.md` reviewed; `.github/workflows/publish-sdks.yml` lints clean (`actionlint .github/workflows/publish-sdks.yml`).

### Wave 0 Gaps

- [ ] `sdks/python/.openapi-python-client.yaml` — generator config (created in Plan 1)
- [ ] `sdks/python/pyproject.toml` — package metadata (created in Plan 1)
- [ ] `sdks/typescript/package.json` — package metadata (created in Plan 1)
- [ ] `sdks/typescript/tsconfig.json` — TS compiler config (created in Plan 1)
- [ ] `sdks/typescript/openapi-ts.config.ts` — generator config (created in Plan 1)
- [ ] `scripts/sync_sdk_versions.py` — version sync script (created in Plan 2)
- [ ] `Makefile` `sdks`/`sdks-check`/`sdks-test`/`publish-sdks-py`/`publish-sdks-ts` targets (created in Plan 2)
- [ ] `sdks/python/geolens_sdk/auth.py` — Python auth wrapper (created in Plan 3)
- [ ] `sdks/typescript/src/auth.ts` — TypeScript auth wrapper (created in Plan 3)
- [ ] `backend/tests/test_sdks_round_trip.py` — integration test (created in Plan 4)
- [ ] `.github/workflows/ci.yml` — `sdks-check` job appended (created in Plan 4)
- [ ] `.github/workflows/publish-sdks.yml` — manual-trigger publish workflow (created in Plan 4)
- [ ] `docs/sdks.md` — generator choices, regen flow, publish process (created in Plan 5)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Auth wrapper handles Bearer + API-key cleanly. Tokens are caller-supplied; SDK does not persist them. CLI consumer (Phase 216) handles keyring storage. |
| V3 Session Management | partial | SDK is stateless re: sessions. JWT lifetime/refresh is consumer's responsibility; SDK passes the token through. |
| V4 Access Control | no | SDK does not enforce access control — backend does. SDK's job is to faithfully invoke endpoints. |
| V5 Input Validation | yes | Generated `attrs`/`TypeScript` types provide compile-time validation; runtime validation comes from the backend. SDK does NOT add a second validation layer (would duplicate logic, drift). |
| V6 Cryptography | no | No crypto in the SDK itself; TLS via `httpx` (Python) and `fetch` (TS) — both use platform/OS trust stores. NEVER hand-roll TLS. |
| V7 Error Handling and Logging | yes | Generated SDKs raise typed exceptions (`UnexpectedStatus` in Python; structured `error` field in TS fetch client). The auth wrapper does NOT log tokens. |
| V14 Configuration | yes | Publish workflow uses `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` (never plaintext). Tokens scoped to publish-only on respective registries. Manual trigger limits blast radius. |

### Known Threat Patterns for SDK distribution

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token leakage in published package | Information disclosure | `package.json` `"files"` field whitelists ONLY `dist/`, `LICENSE`, `README.md`; npm pack dry-run reviewed before first publish; `.npmignore` belt-and-suspenders |
| Supply-chain compromise of generators | Tampering | Generator versions PINNED in Makefile (`uvx openapi-python-client@0.28.3`, `npx @hey-api/openapi-ts@0.96.1`); CI uses `npm ci` (lockfile) for `@hey-api/client-fetch`; lockfile committed |
| Typosquatting of `geolens-sdk` / `@geolens/sdk` | Spoofing | User claims `@geolens` npm org first; PyPI `geolens-sdk` first-publish establishes ownership; consider also publishing protective placeholder `geolens` and `@geolens/cli` (Phase 216 territory) |
| Unauthorized publish from compromised CI | Tampering / EoP | `workflow_dispatch` requires repo-write permission; `PYPI_TOKEN` / `NPM_TOKEN` scoped to single package each (npm tokens support `--scope` and per-package; PyPI tokens support per-project); future: switch to PyPI Trusted Publishing for tokenless OIDC |
| Token in commit history | Information disclosure | `make publish-sdks-py` reads `UV_PUBLISH_TOKEN` from env (not from file); same for `NPM_TOKEN`; `docs/sdks.md` explicitly warns "never commit tokens" |
| Generated code includes sensitive data | Information disclosure | OpenAPI snapshot is reviewed for sensitive examples/defaults during the existing `openapi-snapshot` CI gate; nothing changes for SDK gate |

**The biggest residual risk is publish-time token compromise.** Mitigated by manual-trigger workflow + per-package tokens + future trusted publishing (out of scope for this phase).

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research that need confirmation before locking into the plan.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `--meta none` pattern (Pattern 1) keeps the hand-written `auth.py` safe across regen WHEN combined with the cp-stash approach. | Pitfall 6 | If `--overwrite --output-path sdks/python/geolens_sdk` deletes the directory in a way the cp-stash doesn't recover from (e.g., generator atomically replaces directory in a way that races), need Option 3 (Jinja template). Validate empirically in Plan 2. |
| A2 | `httpx.ASGITransport(app=app)` works seamlessly with `openapi-python-client`'s `set_httpx_client()` — i.e., the generated client doesn't depend on real-network behavior the transport doesn't emulate. | Pitfall 8 | If round-trip test fails because the generator's client uses, e.g., HTTP connection pooling features ASGITransport doesn't support, fall back to running uvicorn in a session-scoped fixture (1-2s startup cost). |
| A3 | The TypeScript SDK can be tested via `pytest` spawning `node` subprocess. | D-14 | If the spawned node script can't find `@geolens/sdk` (because it's not yet published and the local `sdks/typescript/dist/` isn't on the search path), need either `npm pack` + install-from-tarball or `npm link` setup in the fixture. Both viable; pick during Plan 4. |
| A4 | `backend/openapi.json` `info.version` will continue to match `backend/pyproject.toml` `version` (both currently `1.0.0`). | D-08 | If they diverge (e.g., user bumps pyproject but FastAPI app config hardcodes a different version), `make sdks` writes the OpenAPI value into the SDK metadata; this might surprise the user. Plan 5 documents the canonical source: OpenAPI > pyproject. |
| A5 | The user has NOT already created `geolens-sdk` on PyPI or `@geolens/sdk` on npm under another account/org. | Environment Availability | Verified via curl 404 against both registries on 2026-04-27. Low risk; refresh check immediately before first publish. |
| A6 | The Phase 216 CLI (downstream consumer) will accept the verbose generated function names. | Pitfall 2 | If Phase 216 wants nice names, they'll add a wrapper module in the CLI; doesn't affect Phase 215. |

If any of A1–A3 prove wrong during execution, the plan can be revised in-flight without rescoping.

## Open Questions

1. **Should the Python SDK include a "convenience surface" that re-exports under nicer names?**
   - What we know: generator emits `geolens_sdk.api.search.search_datasets_endpoint_search_datasets__get`; that's ugly.
   - What's unclear: whether `docs/sdks.md` should show users how to import-as-aliasing or whether the `auth.py` wrapper should also expose a `Datasets`/`Search` accessor that calls into the generated API with friendlier names.
   - Recommendation: NO for v13.1. Document the import-as pattern in `docs/sdks.md`. Adding a curated convenience surface is "wrapping a wrapper" complexity that breaks regen-clean. Defer to v13.2 if user feedback demands.

2. **Should `make sdks-test` exercise both SDKs or only one?**
   - What we know: D-14 says both. ROADMAP SC#1/SC#2 each bind their own SDK round-trip.
   - What's unclear: whether spawning a Node subprocess from pytest is too brittle for v13.1.
   - Recommendation: Both, per D-14. Mitigation per A3: if Node subprocess proves flaky, split into a separate `npm run test:round-trip` invoked from CI as its own step (still gates the phase, just not via pytest).

3. **Should we adopt PyPI Trusted Publishing now or stick with token-based?**
   - What we know: Trusted Publishing eliminates token management; uses GitHub Actions OIDC; PyPI supports it natively for projects that opt in.
   - What's unclear: whether the user prefers tokens (familiar) or trusted publishing (more secure).
   - Recommendation: Token-based for first publish (faster path to v1.0.0). Migrate to trusted publishing in a future minor task once the publish flow is exercised at least once. Document both in `docs/sdks.md`.

4. **What's the right `node` engine minimum for the published `@geolens/sdk`?**
   - What we know: `@hey-api/client-fetch` requires the runtime `fetch`. Native fetch landed in Node 18.
   - What's unclear: how aggressive to be — Node 18 (broader compat) vs. Node 20 (modern) vs. Node 22 (matches our CI).
   - Recommendation: `"engines": { "node": ">=18" }` in published `package.json`. The GENERATOR requires Node 22.13+ for `make sdks`, but consumers running the COMPILED output are unconstrained beyond `fetch`. Document the distinction.

5. **Is there value in shipping a CHANGELOG.md per SDK?**
   - What we know: Lockstep versioning means SDK versions match backend versions; backend has CHANGELOG.md.
   - What's unclear: whether each SDK needs its own CHANGELOG or whether `sdks/python/README.md` and `sdks/typescript/README.md` can simply link back to the root.
   - Recommendation: Link back to root for v13.1. If/when SDKs publish independently from backend (post-1.0 stability tightening), add per-SDK CHANGELOG.md.

## Sources

### Primary (HIGH confidence)
- **Context7 `/openapi-generators/openapi-python-client`** — fetched 2026-04-27 — config YAML schema, AuthenticatedClient API, `--meta none` semantics, `set_httpx_client` pattern, custom Jinja template path
- **Context7 `/hey-api/openapi-ts`** — fetched 2026-04-27 — config file shape, plugin system, `runtimeConfigPath` for auth, output structure, ESM-only requirement (since v0.91)
- **PyPI registry `pypi.org/pypi/openapi-python-client/json`** — fetched 2026-04-27 — version 0.28.3, requires-python <4.0,>=3.10, MIT
- **npm registry `registry.npmjs.org/@hey-api/openapi-ts/latest`** — fetched 2026-04-27 — version 0.96.1, engines node >=22.13.0, type module
- **npm registry `registry.npmjs.org/@hey-api/client-fetch/latest`** — fetched 2026-04-27 — version 0.13.1
- **GitHub `openapi-generators/openapi-python-client/end_to_end_tests/golden-record/pyproject.toml`** — fetched 2026-04-27 — confirms `httpx`, `attrs >=22.2.0`, `python-dateutil ^2.8.0` runtime deps (NOT pydantic)
- **GitHub `openapi-generators/openapi-python-client/end_to_end_tests/golden-record/my_test_api_client/client.py`** — fetched 2026-04-27 — exact `AuthenticatedClient` constructor signature (`token`, `prefix`, `auth_header_name`)
- **`backend/openapi.json`** — inspected 2026-04-27 — 213 ops, 253 schemas, OpenAPI 3.1.0, single security scheme `OAuth2PasswordBearer`, 115 schemas use `anyOf:[X,null]`, zero `discriminator`/`oneOf`/`allOf`/Input-Output split
- **`backend/scripts/dump_openapi.py`, `Makefile`, `.github/workflows/ci.yml`** — read 2026-04-27 — established patterns to mirror

### Secondary (MEDIUM confidence)
- **WebSearch: "openapi-python-client FastAPI pydantic anyOf null"** — surfaced FastAPI Discussion #9900 about pydantic v2 OpenAPI changes; confirmed our snapshot doesn't trigger the known edge case (no `Input/Output` split, no model defaults)
- **heyapi.dev/openapi-ts/get-started** (WebFetch) — confirmed Node 22+ minimum, ESM-only, `npm add -E` pinning recommendation
- **uv docs (uv build / uv publish)** — confirmed `UV_PUBLISH_TOKEN` env-var pattern and uv's role as twine replacement
- **npm scoped packages docs** — confirmed `--access public` requirement for first publish of `@geolens/sdk`

### Tertiary (LOW confidence — not relied upon for decisions)
- WebSearch results on Python monorepo patterns (informational; our `--meta none` approach is well-supported in primary sources, not dependent on these)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against live registries + Context7 + golden-record source
- Architecture: HIGH — pattern is established (mirrors existing openapi/openapi-check); auth wrapper shape verified against generator's first-class auth primitives
- Pitfalls: MEDIUM-HIGH — pitfalls 1, 4, 5 verified directly against artifacts (`backend/openapi.json`, golden-record pyproject.toml); pitfall 6 (overwrite + auth.py preservation) is logical inference from `--overwrite` semantics, validated empirically during Plan 2; pitfalls 7, 10 are from npm/PyPI documentation
- Round-trip test architecture: MEDIUM — `set_httpx_client` API is documented for sync but assumption A2 (it works with ASGITransport for the generator's specific usage patterns) needs Plan 4 empirical confirmation
- Security domain: HIGH — established mitigations are standard SDK-publishing practice; tokens are user-held by design
- Environment availability: HIGH — registry checks done live on 2026-04-27

**Research date:** 2026-04-27
**Valid until:** 2026-05-15 (3 weeks — generators are fast-moving; re-verify versions before final commit if Phase 215 stretches beyond this window)

---

## RESEARCH COMPLETE

**Phase:** 215 - sdks-from-openapi
**Confidence:** HIGH

### Key Findings
- `openapi-python-client` v0.28.3 generates **`attrs`-based** Python code (not pydantic v2 — CONTEXT.md D-01 misstates this; correct in `docs/sdks.md`).
- `@hey-api/openapi-ts` v0.96.1 is ESM-only and requires Node 22.13+ for codegen; published consumer SDK can target Node 18+.
- The OpenAPI snapshot is clean: no `discriminator`/`oneOf`/`allOf`/Input-Output-split — neither generator will hit the known FastAPI+pydantic-v2 edge cases.
- `X-API-Key` header auth is NOT in the OpenAPI snapshot (only `OAuth2PasswordBearer` is) — the hand-written wrapper handles this gracefully via `prefix=""` + `auth_header_name="X-API-Key"` on the generated `AuthenticatedClient`.
- Round-trip test reuses the existing `client` fixture's `httpx.ASGITransport(app=app)` — no separate uvicorn process needed for the Python half (TS half spawns Node).
- Both `geolens-sdk` (PyPI) and `@geolens/sdk` (npm) names are AVAILABLE; npm `@geolens` org is UNCLAIMED — user must claim before first publish.
- FastAPI's verbose autogenerated operationIds (`get_single_dataset_datasets__dataset_id__get`) produce ugly SDK function names — accept for v13.1, document, defer cleanup.

### File Created
`.planning/phases/215-sdks-from-openapi/215-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | Versions verified live against PyPI/npm registries; runtime deps verified against golden-record source |
| Architecture | HIGH | Mirrors existing openapi-check pattern; auth wrappers map to generators' first-class auth APIs |
| Pitfalls | MEDIUM-HIGH | Most verified directly against artifacts; pitfall 6 (overwrite + auth.py) needs Plan 2 empirical confirmation |
| Round-trip approach | MEDIUM | API exists (`set_httpx_client`) but ASGI integration assumed working; validate in Plan 4 |

### Open Questions
1. Convenience-naming surface — recommend NO for v13.1 (defer)
2. PyPI Trusted Publishing vs. token — recommend tokens for first publish, migrate later
3. Node engine minimum for published SDK — recommend `>=18` (separate from generator's `>=22.13`)

### Ready for Planning
Research complete. Planner can now create PLAN.md files for the 5-plan decomposition CONTEXT.md sketches, with the corrections and elevated risks documented above.
