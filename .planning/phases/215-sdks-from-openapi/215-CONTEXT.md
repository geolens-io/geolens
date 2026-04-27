# Phase 215: sdks-from-openapi - Context

**Gathered:** 2026-04-27 (auto-mode — Claude judgment for all gray areas)
**Status:** Ready for planning

<domain>
## Phase Boundary

External integrators (and the v13.1 CLI in Phase 216) consume GeoLens through auto-generated Python + TypeScript SDKs derived from `backend/openapi.json`. SDK drift against the snapshot is gated by CI via `make sdks-check` (mirrors the existing `make openapi-check` pattern at `backend/scripts/dump_openapi.py`).

After this phase:
- `sdks/python/` contains a generated Python package `geolens-sdk` with typed clients, pydantic v2 models, and Bearer-token + API-key auth helpers.
- `sdks/typescript/` contains a generated TypeScript package `@geolens/sdk` with typed request/response interfaces and the same auth helpers.
- Top-level `Makefile` has `make sdks` (regenerates both SDKs), `make sdks-check` (regenerates and fails on `git diff --exit-code sdks/`), and `make sdks-test` (round-trip integration check against a running api instance).
- CI workflow extends to run `make sdks-check` on every PR.
- `docs/sdks.md` documents generator choices, version-pin policy, and release process.
- Both SDKs publish under Apache-2.0; the publishing infrastructure is wired (GitHub Actions workflow + `make publish-sdks-py` / `make publish-sdks-ts` recipes), but **actual publishing to PyPI/npm requires the user's credentials and is a manual user action** (out of scope for autonomous execution — see deferred section).

In scope: SDK generation tooling, auth helper wrappers, drift gate, integration round-trip test, release-process docs, GitHub Actions publish workflow scaffold (with manual trigger).

Out of scope: actual v1.0.0 PyPI/npm publication (requires user-held tokens), hand-tuned SDK code (use generator templates only), backwards-compat pinning across multiple backend versions (lockstep policy locks SDK version to backend version), full SDK documentation site (Phase 216's `docs/` work or a future docs-site phase), CLI implementation (Phase 216).

</domain>

<decisions>
## Implementation Decisions

### Generator selection
- **D-01:** **Python generator: `openapi-python-client`** (https://github.com/openapi-generators/openapi-python-client). Rationale: modern (active 2024-2026), pydantic v2 native (matches our backend's pydantic), async-first via httpx, generates idiomatic typed clients without the JVM dependency `openapi-generator` (Java) requires. Single dependency, runs via `uvx openapi-python-client generate ...`. Generated output structure: `sdks/python/geolens_sdk/{api,models,client.py,__init__.py}`.
- **D-02:** **TypeScript generator: `@hey-api/openapi-ts`** (https://github.com/hey-api/openapi-ts). Rationale: actively-maintained successor of `openapi-typescript-codegen`, fast, customizable templates, emits both fetch- and axios-flavored clients, native ESM + TypeScript 5+ support, no Java toolchain. Single npm dependency, runs via `npx @hey-api/openapi-ts ...`. Generated output: `sdks/typescript/src/{client,services,models,index.ts}` plus `package.json`/`tsconfig.json`/`README.md` scaffolding.
- **D-03:** **No fallback to `openapi-generator` (Java)** despite it being more mature. Reason: requires JVM at build time (extra CI dependency), generates more verbose code that diverges from project's modern Python idioms. If D-01 or D-02's tool produces unworkable output for a specific schema feature, the planner may revisit; default is hold.

### Package layout
- **D-04:** **In-repo monorepo** at `sdks/python/` and `sdks/typescript/`. Reason: single source of truth, atomic commits coupling backend route changes with SDK regeneration, no cross-repo synchronization burden. Each subdirectory is a self-contained package (own `pyproject.toml` / `package.json`) so PyPI and npm publishing flows pull from there directly.
- **D-05:** Package names follow ROADMAP wording exactly: PyPI `geolens-sdk` (importable as `geolens_sdk`), npm `@geolens/sdk` (scoped under `@geolens` org). The `@geolens` npm scope must exist before publish — that's a one-time user setup.
- **D-06:** Both packages declare `Apache-2.0` license. `LICENSE` files copy the project's root LICENSE verbatim. ROADMAP SC#1, SC#2 bind this.

### Versioning + release process
- **D-07:** **Lockstep versioning** with the backend OpenAPI snapshot. Both SDKs' version = `backend/openapi.json`'s `info.version` field at the time of generation. Each SDK package emits a `__version__` constant (Python) / `version` export (TS) embedding the OpenAPI version. Reason: the SDK is a derived artifact; if backend ships v1.4.2, both SDKs publish v1.4.2 within the same release window. Independent semver would create user confusion.
- **D-08:** Version-pin enforcement: the SDK regeneration script writes the OpenAPI version into the SDK's `pyproject.toml` / `package.json` as part of `make sdks`. CI's `make sdks-check` therefore catches version drift along with code drift in a single gate.
- **D-09:** `docs/sdks.md` (NEW) documents: (a) which generator was selected and why (D-01, D-02), (b) `make sdks` regeneration flow, (c) version-pin policy, (d) publish process (`make publish-sdks-py` / `make publish-sdks-ts` requires `PYPI_TOKEN` / `NPM_TOKEN` env vars; tokens are user-managed, NOT committed to repo). Closes OCSDK-04.

### Auth helpers
- **D-10:** **Auth helper layer added as a thin hand-written wrapper** in each SDK, NOT generated. The generators emit auth-agnostic clients accepting `httpx.Client` (Python) / `fetch` config (TS) which the wrapper sets up. Wrappers expose:
  - Python: `GeolensClient(base_url: str, *, bearer_token: str | None = None, api_key: str | None = None)` constructor; mutating helpers `set_bearer_token(...)`, `set_api_key(...)`. Bearer goes to `Authorization: Bearer <token>` header; API key goes to `X-API-Key` header (matches backend's `_resolve_api_key()` precedence: header > query > JWT > anonymous).
  - TypeScript: `createGeolensClient({ baseUrl, bearerToken?, apiKey? })` factory; same header semantics.
  - Both wrappers live at `sdks/{python,typescript}/src/.../auth.py|ts` and are NOT regenerated by `make sdks` — they import the generated client and configure it. The `make sdks-check` drift gate explicitly excludes the auth wrapper file via `git diff --exit-code sdks/ ':!sdks/python/geolens_sdk/auth.py' ':!sdks/typescript/src/auth.ts'` (or equivalent).
- **D-11:** Auth wrapper behavior matches CLAUDE.md note: API key fallback via `?api_key=<key>` query param IS supported by the backend but the SDK wrapper uses headers only (cleaner; query param fallback is for browser/embed contexts the SDK does not target).

### Drift gate
- **D-12:** **Drift gate mechanism mirrors `make openapi-check`.** Top-level `Makefile` adds:
  ```makefile
  sdks: ## Regenerate Python + TypeScript SDKs from backend/openapi.json
  	cd backend && uv run python scripts/dump_openapi.py  # ensure snapshot is fresh
  	uvx openapi-python-client generate --path backend/openapi.json --output-path sdks/python/ --overwrite --config sdks/python/.openapi-python-client.yaml
  	cd sdks/typescript && npx --yes @hey-api/openapi-ts -i ../../backend/openapi.json -o src/ -c @hey-api/client-fetch
  	# Pin SDK package versions to OpenAPI version
  	python scripts/sync_sdk_versions.py

  sdks-check: ## Fail CI if SDK regeneration produces a diff
  	$(MAKE) sdks
  	git diff --exit-code -- sdks/ \
  	  ':!sdks/python/geolens_sdk/auth.py' \
  	  ':!sdks/typescript/src/auth.ts' \
  	  ':!sdks/python/README.md' \
  	  ':!sdks/typescript/README.md'

  sdks-test: ## Round-trip both SDKs against running api
  	cd backend && uv run pytest tests/test_sdks_round_trip.py -v
  ```
  Closes OCSDK-03.
- **D-13:** **Hand-written files exempted from drift gate** (excluded via `:!` pathspec): the auth wrapper modules (D-10), README files (manual prose), and `pyproject.toml`/`package.json` (the version-sync script touches version field but the rest is hand-maintained). This is the standard pattern for "generator + thin wrapper" architectures.

### Integration round-trip test
- **D-14:** A new pytest module `backend/tests/test_sdks_round_trip.py` (NEW) tests both SDKs against a running api instance:
  - Python SDK: imports `geolens_sdk`, configures Bearer auth using a generated test JWT, hits `GET /search/datasets`, `GET /datasets/{id}`, `POST /ingest` (with a tiny GeoJSON fixture). Assertions: 200 OK + minimum response shape per the OpenAPI schema. ROADMAP SC#1 binds these three endpoints.
  - TypeScript SDK: pytest spawns `node` running a small TypeScript test script (`sdks/typescript/test/round_trip.test.ts`) compiled inline; checks the same three endpoints. ROADMAP SC#2 binds.
  - The pytest fixture uses the existing `client` fixture pattern from `backend/tests/conftest.py` to spin up the test api; the SDK calls hit it directly via `httpx`. No docker compose round-trip needed in CI; this is a unit-style integration test.

### CI workflow
- **D-15:** **GitHub Actions extension** — add a new job `sdks-check` to the existing `.github/workflows/*.yml` (alongside `openapi-snapshot` job). Job steps: checkout → setup Python 3.13 + uv → setup Node 20+ → install `openapi-python-client` and `@hey-api/openapi-ts` → run `make sdks-check`. Fails CI if regeneration produces a diff against committed `sdks/`.
- **D-16:** **Publish workflow `.github/workflows/publish-sdks.yml` (NEW)** — manual-trigger workflow (`workflow_dispatch`) that builds and uploads both packages to PyPI / npm. Uses `secrets.PYPI_TOKEN` / `secrets.NPM_TOKEN` (user-configured GitHub secrets). Triggered manually only — automatic publication on merge is risky for SDKs, especially during early adoption. Phase 215 ships the workflow scaffold; user-triggered first publish is a separate manual action.

### Boundary with Phase 216
- **D-17:** Phase 216 (geolens-cli-mvp) consumes the Python SDK. Phase 215 does NOT add CLI code. The Python SDK's `pyproject.toml` exposes `geolens_sdk` as the importable package; Phase 216's `geolens` CLI package depends on `geolens-sdk>={version}` (lockstep version pinning per D-07). This is OCCLI-06 (CLI uses generated SDK, no hand-rolled HTTP). Phase 216 publishes a SEPARATE PyPI package `geolens` (the CLI) that depends on `geolens-sdk` (the SDK).

### Claude's Discretion (planner picks)
- **Commit decomposition** — likely 4-5 plans: (1) scaffold `sdks/python/` + `sdks/typescript/` directories with empty README + tooling configs (`.openapi-python-client.yaml`, `package.json`, `tsconfig.json`); (2) wire `make sdks` + `make sdks-check` + the version-sync script + run first regeneration to commit baseline generated code; (3) add Python + TypeScript auth wrappers (`auth.py`/`auth.ts`); (4) add round-trip test (`backend/tests/test_sdks_round_trip.py`) + CI job + `publish-sdks.yml` workflow scaffold; (5) write `docs/sdks.md` + phase verification gate. Planner may collapse 3+4 if the wrappers are minimal.
- **TypeScript build target** — D-02 picks `@hey-api/client-fetch` over the axios variant; if the planner finds an integration issue (e.g., Node 18 fetch quirks), they may switch to axios.
- **Whether to commit generated code** — YES, default. Generated code is committed so consumers can `git clone` and inspect; the drift gate enforces freshness. Alternative ("regenerate-on-install") is rejected because it forces consumers to install Java/Node tooling.
- **Bun vs npm for TypeScript build** — npm. The frontend uses npm (`frontend/package-lock.json`); SDK follows suit. Bun would be faster but adds a new tool the project doesn't otherwise need.
- **Whether to run the publish workflow as part of Phase 215** — NO. Phase 215 ships infrastructure only. Actual publish is a user action (requires PYPI_TOKEN, NPM_TOKEN, and review of generated package contents).

</decisions>

<canonical_refs>
## Canonical References

### Audit / spec
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 row "Auto-generate Python + TS SDKs from snapshotted OpenAPI" (3-5d effort).
- `docs-internal/audits/oc-separation-audit-20260426.md` §6 — full audit context. Names this as the developer-adoption-wedge move.
- `.planning/REQUIREMENTS.md` §OCSDK-01..04 — the four requirements this phase closes.
- `.planning/ROADMAP.md` §Phase 215 — goal + 4 success criteria.

### Project / state
- `.planning/PROJECT.md` — milestone overview; v13.1 target grade Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 215 contributes to OSS Surface (the developer adoption wedge).
- `.planning/STATE.md` — confirms 1988-test backend baseline post-Phase-214.
- `.planning/phases/214-identity-protocol-extract/214-CONTEXT.md` — companion just-shipped phase; Phase 215 is independent (touches different files entirely).

### Code (existing)
- `backend/openapi.json` — the source of truth (already committed; sorted keys + trailing newline; deterministic).
- `backend/scripts/dump_openapi.py` — the precedent pattern for `make openapi-check`. Phase 215's `sdks-check` mirrors its `--check` flag semantics.
- `Makefile` (root) — has `openapi`, `openapi-check` targets at the top of `.PHONY`. Phase 215 extends.
- `.github/workflows/*.yml` — existing `openapi-snapshot` job. Phase 215 adds `sdks-check` job.
- `frontend/package.json`, `frontend/package-lock.json` — npm precedent.
- `backend/pyproject.toml` — Python packaging precedent (uv-based, Apache-2.0 license).

### Code (new)
- `sdks/python/` — NEW directory, generated Python SDK
- `sdks/typescript/` — NEW directory, generated TypeScript SDK
- `sdks/python/geolens_sdk/auth.py` — NEW hand-written auth wrapper
- `sdks/typescript/src/auth.ts` — NEW hand-written auth wrapper
- `sdks/python/.openapi-python-client.yaml` — NEW generator config
- `scripts/sync_sdk_versions.py` — NEW version-pin script
- `backend/tests/test_sdks_round_trip.py` — NEW integration test
- `.github/workflows/publish-sdks.yml` — NEW publish workflow scaffold
- `docs/sdks.md` — NEW SDK documentation

### Generator docs
- https://github.com/openapi-generators/openapi-python-client (D-01)
- https://github.com/hey-api/openapi-ts (D-02)
- https://heyapi.dev/openapi-ts/get-started.html — usage docs

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/scripts/dump_openapi.py`** — the model for the SDK regeneration scripts. Idempotent, deterministic output, `--check` flag semantics. Phase 215's `make sdks` mirrors this style.
- **`Makefile` `openapi`/`openapi-check` pair** — exact precedent for `sdks`/`sdks-check`. Same `cd backend && uv run` pattern.
- **`.github/workflows/*.yml` `openapi-snapshot` job** — exact precedent for the new `sdks-check` job. Same `setup-python` + `setup-node` shape.
- **Backend FastAPI route definitions** drive the OpenAPI schema. No SDK-side changes required when routes change — `make sdks` regenerates and CI's drift gate catches mismatches.

### Established Patterns
- **Apache-2.0 license** — root `LICENSE` file copied verbatim into both SDK packages.
- **uv for Python tooling** — `uvx openapi-python-client` (one-off invocation, no global install).
- **npm for Node tooling** — `npx --yes @hey-api/openapi-ts` (one-off invocation).
- **Sorted-keys JSON output** — `backend/openapi.json` uses this for diff stability. SDK regeneration must NOT reorder schema keys.

### Risk surfaces
- **Generator template breaks on edge schema features** — e.g., FastAPI's discriminated unions, polymorphic responses, or `extra` fields may produce unworkable code. Mitigation: round-trip test (D-14) catches it; planner can switch generator if it surfaces.
- **Generated code drift on backend hot-paths** — every PR that touches a route also touches `openapi.json` (via `openapi-check` gate) AND now `sdks/` (via `sdks-check` gate). Developer ergonomics: both regenerations are one `make sdks` away.
- **TypeScript ESM + Node 18 fetch interop** — `@hey-api/client-fetch` defaults to native fetch (Node 18+); if a consumer is on Node 16 or older, they need a polyfill. Documented in `docs/sdks.md` minimum-version section.
- **Circular dependency risk** — Phase 216 CLI depends on Python SDK; SDK does NOT depend on CLI. Lockstep versioning makes this clean.

</code_context>

<specifics>
## Specific Ideas

- **Why NOT openapi-generator (Java)** — chosen alternatives (D-01, D-02) avoid the JVM dependency that `openapi-generator-cli.jar` imposes. CI ergonomics and contributor onboarding both benefit.
- **Why NOT a separate `geolens-sdk` repo** — see D-04. Single source of truth + atomic backend-and-SDK commits beat repo-isolation hygiene at this scale.
- **Why lockstep versioning** — see D-07. SDK is a derived artifact; independent semver is solving a problem we don't have (and creating one — version-skew confusion).
- **Why manual-trigger publish workflow** — see D-16. Auto-publish on merge is fine for backend deploys but risky for SDKs while the API surface is stabilizing toward 1.0.

</specifics>

<deferred>
## Deferred Ideas

- **Actual v1.0.0 publication to PyPI/npm** — Phase 215 wires the publish workflow + Makefile recipes; pressing the trigger requires the user's PyPI and npm tokens (one-time creation in those services + GitHub secret upload). NOT autonomous-executable; left as a documented user action in `docs/sdks.md`.
- **`geolens.yaml` catalog manifest spec** — `OCSDK-05` in REQUIREMENTS.md; deferred to P2 per the audit. Out of scope.
- **SDK documentation site** — generated `pdoc` / `typedoc` pages, hosted somewhere. Not required by SC; `docs/sdks.md` is the v13.1 deliverable. Future phase.
- **OpenAPI 3.1 polymorphism / discriminator handling** — if the chosen generators struggle with a specific schema feature, the planner may pin to OpenAPI 3.0 output or hand-tune templates. Rare; cross that bridge if hit.
- **Backwards compat across multiple backend versions** — D-07 lockstep policy says no. If a real consumer needs to pin SDK 1.2.x against backend 1.4.x, that's a future requirement.
- **CI auto-publish on tag push** — Phase 215's workflow is `workflow_dispatch` (manual). Future tightening to "publish-on-tag" is fine once the SDK is stable; D-16's manual trigger is the v13.1 default.
- **Browser bundle of TypeScript SDK** — `@hey-api/openapi-ts` outputs ESM compatible with bundlers; explicit browser-bundle (CDN-loadable IIFE) is out of scope. Frontend consumers use npm + bundler.
- **Frontend migration to use the generated TS SDK** — tempting (would replace the hand-written `frontend/src/api/client.ts`), but a separate concern with frontend-specific risks. Deferred.

</deferred>

---

*Phase: 215-sdks-from-openapi*
*Context gathered: 2026-04-27 (auto-mode)*
