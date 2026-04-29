---
phase: 215-sdks-from-openapi
plan: 04
subsystem: infra
tags: [openapi, sdk, python, typescript, integration-test, ci, github-actions, drift-gate, publish-workflow, asgi-transport]

# Dependency graph
requires:
  - phase: 215-03
    provides: GeolensClient (Python wrapper exposing AuthenticatedClient with bearer/api-key/anonymous modes); createGeolensClient (TypeScript factory configuring the @hey-api singleton); compiled TS dist/ with createGeolensClient declaration; existing Makefile sdks-check target with :! pathspec exemptions for hand-written wrappers
provides:
  - backend/tests/test_sdks_round_trip.py — pytest module with 7 GeolensClient unit tests + 4 round-trip Python tests (search/datasets/, datasets/{id}, ingest/upload, X-API-Key auth) + 1 TypeScript subprocess test (spawns uvicorn on free port + node round_trip.test.mjs)
  - sdks/typescript/test/round_trip.test.mjs — Node script invoked by pytest subprocess; exercises the same three endpoints via createGeolensClient + generated SDK functions
  - .github/workflows/ci.yml — extended with `sdks-check` job that mirrors openapi-snapshot job's shape; runs `make sdks-check` on every PR touching backend/ + every push to main
  - .github/workflows/publish-sdks.yml — new workflow_dispatch-only manual-trigger workflow with python/typescript/both targets, dry_run boolean, and per-package secrets (PYPI_TOKEN/NPM_TOKEN); `npm publish --access public` per Pitfall 10
  - Empirical confirmation that ASGITransport works end-to-end for the Python SDK (via async path only — sync path errors)
  - Empirical confirmation that X-API-Key auth flows through GeolensClient despite not being in the OpenAPI spec (closes Pitfall 4)
  - Empirical confirmation that the Node subprocess + uvicorn-on-free-port pattern works in pytest (closes Assumption A3)
affects:
  - 215-05 (docs/sdks.md must document: round-trip test layout for contributors, the body=None workaround for optional GET bodies, the asyncio_detailed-only path for in-process testing, and the manual-publish-with-tokens runbook)
  - All future PRs (every backend change now triggers `sdks-check` in CI; drift in generated SDK code blocks merge)

# Tech tracking
tech-stack:
  added:
    - SDK round-trip integration test (pytest + Node subprocess) — first cross-language test in the repo
    - GitHub Actions sdks-check job (drift gate at CI level)
    - GitHub Actions manual publish workflow (workflow_dispatch with target/dry_run inputs)
  patterns:
    - "ASGITransport for in-process Python SDK testing — wire AuthenticatedClient.set_async_httpx_client() with a manually-built httpx.AsyncClient that includes the auth header up front (the lazy header injection in get_async_httpx_client is bypassed when set_*_httpx_client is called directly)"
    - "asyncio.to_thread for blocking subprocess.run inside an async test — without it, the subprocess deadlocks against the same event loop that's serving uvicorn for the subprocess to call into"
    - "uvicorn.Server bound to 127.0.0.1:0 (free-port pick) for one-shot pytest tests that need a real HTTP server (TS subprocess can't share the in-process ASGI app)"
    - "lifespan='off' on the in-test uvicorn config — bypasses startup hooks that would race with the test fixture's DB overrides"

key-files:
  created:
    - backend/tests/test_sdks_round_trip.py
    - sdks/typescript/test/round_trip.test.mjs
    - .github/workflows/publish-sdks.yml
    - .planning/phases/215-sdks-from-openapi/215-04-SUMMARY.md
  modified:
    - .github/workflows/ci.yml (added sdks-check job between openapi-snapshot and backend-test)

key-decisions:
  - "Implemented D-14: round-trip integration test exists at backend/tests/test_sdks_round_trip.py with 12 tests total — 7 GeolensClient unit (no network), 4 Python round-trip (search, get-single-dataset, ingest-upload, api-key-auth-mode), 1 TypeScript subprocess. ROADMAP SC#1 + SC#2 closed empirically."
  - "Implemented D-15: ci.yml gains a `sdks-check` job that mirrors the openapi-snapshot job's shape (setup-uv@v6 + setup-python@v5 + setup-node@v6) and runs `make sdks-check`. Job is gated by `needs.changes.outputs.backend == 'true' || github.event_name == 'push'` — same as the OpenAPI gate, so any backend change triggers SDK regeneration + drift check."
  - "Implemented D-16: publish-sdks.yml is a workflow_dispatch-only manual-trigger workflow. Two parallel jobs (publish-python, publish-typescript), each gated by a `target` choice input. Dry-run support via `dry_run` boolean input — lets the user verify the build artifacts before pressing publish. Per-package secrets (PYPI_TOKEN/NPM_TOKEN) limit blast radius. `npm publish --access public` flag is explicit per RESEARCH Pitfall 10."
  - "Tests use the SDK's `asyncio_detailed` path (not `sync_detailed`) because `httpx.ASGITransport` only implements `handle_async_request`. The sync path raises AttributeError. Documented inline at the helper docstring so future tests don't trip over it."
  - "subprocess.run is wrapped in asyncio.to_thread inside the TS round-trip test because the in-test uvicorn server runs on the same event loop as the test. Blocking the loop deadlocks the subprocess waiting for the server. asyncio.to_thread offloads the wait to a worker thread."
  - "Search endpoint test passes `body=None` rather than relying on the SDK's UNSET sentinel default. The generator's `_get_kwargs` unconditionally sets `_kwargs[\"json\"] = body`, and httpx fails to JSON-serialize the SDK's `Unset` class. Passing None works because the else branch handles it correctly. This is a known openapi-python-client 0.28.3 quirk for endpoints with optional list bodies on GET routes — documented inline so SDK consumers know the workaround."

patterns-established:
  - "Python SDK round-trip via in-process ASGITransport (no subprocess, no socket) — ~3s for 4 tests including DB-backed admin login + API key creation"
  - "TypeScript SDK round-trip via uvicorn-subprocess + Node-subprocess — ~5s including server start/stop, asyncio.to_thread bridge"
  - "GitHub Actions drift-gate pattern: the regen pipeline runs `make sdks-check` which calls `make sdks` and then `git diff --exit-code` against the generated dirs (with hand-written file exemptions). Mirrors the existing openapi-check pattern."
  - "Manual-publish workflow pattern: `workflow_dispatch` with target choice + dry_run boolean. Tokens are repo secrets, never logged. Per-package access tokens limit blast radius. Future migration path to PyPI Trusted Publishing already wired (id-token: write permission)."

requirements-completed:
  - OCSDK-01
  - OCSDK-02
  - OCSDK-03

# Metrics
duration: 6m 51s
completed: 2026-04-27
---

# Phase 215 Plan 04: Round-trip integration test + CI sdks-check job + manual publish workflow Summary

**SDK round-trip suite at backend/tests/test_sdks_round_trip.py exercises both SDKs end-to-end (Python via in-process ASGITransport, TypeScript via uvicorn subprocess + Node subprocess), the new `sdks-check` job wires the drift gate into every CI run, and `publish-sdks.yml` ships as a manual-trigger workflow ready for first publish once tokens are configured. 12/12 tests pass; `make sdks-check` exits 0; both workflow YAMLs parse clean.**

## Performance

- **Duration:** 6m 51s
- **Started:** 2026-04-27T19:48:56Z
- **Completed:** 2026-04-27T19:55:47Z
- **Tasks:** 2
- **Files committed:** 3 created (test_sdks_round_trip.py, round_trip.test.mjs, publish-sdks.yml) + 1 modified (ci.yml) across two task commits
- **Test counts:** 12 tests pass (7 unit + 4 Python round-trip + 1 TypeScript subprocess), runtime ~5s
- **Lines added:** 377 (test_sdks_round_trip.py) + 95 (round_trip.test.mjs) + 95 (publish-sdks.yml) + 39 (ci.yml diff) = 606 LOC

## Accomplishments

- 7 GeolensClient unit tests pass — bearer/api-key/anonymous construction, mutual-exclusion ValueError, set_bearer_token, set_api_key, .client property
- 4 Python round-trip tests pass — exercise the three OCSDK-01 endpoints via in-process httpx.AsyncClient + ASGITransport, plus a fourth test that creates an API key and verifies X-API-Key auth flows through the wrapper (closes Pitfall 4 empirically)
- 1 TypeScript subprocess test passes — spins up uvicorn on a free port, hands the Node script BASE_URL + JWT, asserts exit 0; uses asyncio.to_thread to avoid event-loop deadlock
- `sdks-check` CI job mirrors the openapi-snapshot job's shape exactly (setup-uv@v6 + setup-python@v5 + setup-node@v6 + cache against sdks/typescript/package-lock.json) and runs `make sdks-check`
- `publish-sdks.yml` is a workflow_dispatch-only manual workflow with target choice (python/typescript/both) + dry_run boolean; `npm publish --access public` flag explicit per Pitfall 10
- Both workflow files parse as valid YAML (`yaml.safe_load`)
- `make sdks-check` exits 0 — no regression to the SDK regeneration pipeline
- ROADMAP SC#1 + SC#2 + SC#3 closed at the integration-test + CI level
- Threat-register T-215-04-01 through T-215-04-08 mitigations all in place (token-mask via secrets, drift-gate-on-push, manual-trigger publish, `npm pack --dry-run` belt-and-suspenders, ASGI in-process for log-clean fixtures, subprocess timeout=30, npm ci on lockfile)

## Task Commits

Each task committed atomically:

1. **Task 1: Round-trip integration test (backend/tests/test_sdks_round_trip.py + sdks/typescript/test/round_trip.test.mjs)** — `d6e97ed9` (test)
2. **Task 2: sdks-check CI job + publish-sdks.yml manual workflow (.github/workflows/ci.yml + .github/workflows/publish-sdks.yml)** — `38f9fdb2` (ci)

**Plan metadata commit:** pending (final commit captures this SUMMARY.md + STATE.md + ROADMAP.md updates)

## Files Created/Modified

### Created

- `backend/tests/test_sdks_round_trip.py` (377 LOC) — pytest module. `TestPythonAuthWrapperUnit` class with 7 unit tests (no network); `TestPythonRoundTrip` class with 4 round-trip tests against the in-process FastAPI app via `httpx.AsyncClient(transport=ASGITransport(app=app))`; standalone `test_typescript_round_trip` that spawns uvicorn on a free 127.0.0.1 port + a Node subprocess. Helper `_wire_asgi_transport` reads token/prefix/auth_header_name off the underlying generated client and constructs the httpx.AsyncClient with the auth header up front (because `set_async_httpx_client` bypasses the lazy injection in `get_async_httpx_client`).

- `sdks/typescript/test/round_trip.test.mjs` (95 LOC) — Node test script. Reads GEOLENS_BASE_URL + GEOLENS_TOKEN from env; imports `createGeolensClient` from `../dist/index.js` and the three target SDK functions from `../dist/client/sdk.gen.js` (verified function names from `dist/client/sdk.gen.d.ts`); calls all three endpoints with status assertions (200 / 404 / non-5xx); exits 0 on success, non-zero with descriptive console.error on failure. Send body via `FormData` + `Blob` (Node 22 native).

- `.github/workflows/publish-sdks.yml` (95 LOC) — `workflow_dispatch:` with `target` choice input (python/typescript/both, default both) and `dry_run` boolean. Two parallel jobs gated by the target input. Python job: `uv build` → list dist → `uv publish` (skipped if dry_run). TypeScript job: `npm ci` → `npm run build` → `npm pack --dry-run` (always, as belt-and-suspenders) → `npm publish --access public` (skipped if dry_run). Tokens via `secrets.PYPI_TOKEN` and `secrets.NPM_TOKEN` mapped into env vars.

- `.planning/phases/215-sdks-from-openapi/215-04-SUMMARY.md` — this file.

### Modified

- `.github/workflows/ci.yml` — added the `sdks-check` job between `openapi-snapshot` (line ~103) and `backend-test` (line ~141). 39 net lines added. The job runs on `needs.changes.outputs.backend == 'true' || github.event_name == 'push'` (same gate as openapi-snapshot), uses setup-uv@v6 with version 0.10.2 + setup-python@v5 with 3.13 + setup-node@v6 with node 22 (cache against sdks/typescript/package-lock.json), installs backend deps via `uv sync --locked --dev`, installs TS deps via `npm ci`, then runs `make sdks-check`. The `JWT_SECRET_KEY: sdks-check-padding-key-32characters-here` env var matches the openapi-snapshot job's pattern (≥32 chars to satisfy the Settings validator).

## Decisions Made

See key-decisions in frontmatter. Highlights:

- **D-14 (round-trip test) implemented with two distinct transports.** The Python half uses ASGITransport for speed (no socket, no subprocess overhead). The TypeScript half can't share that — Node has its own runtime, can't import the FastAPI app, and the @hey-api SDK uses `fetch` against a real URL. So the TS test spins up uvicorn on a free port for one-shot use. Tradeoff is ~2s of startup cost; in exchange we get true cross-runtime end-to-end verification.

- **D-15 (sdks-check CI job) deliberately mirrors openapi-snapshot's shape.** Same `if:` condition (run on backend changes OR pushes to main), same setup-uv version, same Python version, same `working-directory` indirection. The minimum-change approach makes maintenance easy: if openapi-snapshot's bootstrap pattern needs updating (e.g., uv version bump), sdks-check is updated identically.

- **D-16 (publish-sdks.yml) ships scaffold-only, not auto-publish.** `workflow_dispatch` (manual) is the trigger; there is NO `release:` or tag-push trigger. Per RESEARCH §Security and CONTEXT D-16, while the SDK is stabilizing toward 1.0 we want a human in the loop. Migration to auto-publish-on-tag is out of scope for v13.1.

- **`asyncio.to_thread` for the subprocess wrap is non-obvious but necessary.** When pytest's anyio-managed event loop is also serving uvicorn, calling `subprocess.run` directly blocks the loop. The Node script then waits on HTTP requests that uvicorn never gets to process — deadlock until the subprocess timeout fires. `asyncio.to_thread` runs the blocking call in a worker thread; the loop continues to serve uvicorn.

- **`body=None` rather than UNSET on the search SDK call** is a workaround for a real openapi-python-client 0.28.3 quirk: the generator unconditionally sets `_kwargs["json"] = body`, and httpx can't serialize the SDK's `Unset` class. The fix is documented inline in the test so future SDK consumers (Phase 216 CLI in particular) inherit the workaround.

## Deviations from Plan

The plan was executed largely as written. Three Rule-1/3 deviations surfaced during execution; all auto-fixed, all documented inline.

### Auto-fixed Issues

**1. [Rule 3 — Blocking] ASGITransport is async-only; the SDK's sync_detailed path can't use it**

- **Found during:** Task 1, first run of the round-trip tests
- **Issue:** `httpx.ASGITransport` only implements `handle_async_request`. When the SDK's `sync_detailed` calls `client.get_httpx_client().request(...)`, httpx synchronously dispatches via the transport's missing `handle_request` → `AttributeError: 'ASGITransport' object has no attribute 'handle_request'. Did you mean: 'handle_async_request'?`.
- **Why blocking:** The plan's must-haves require round-trip tests to use ASGITransport per CONTEXT D-14. Without resolving this, the tests can't run.
- **Why Rule 3:** Switching from `sync_detailed` to `asyncio_detailed` is a single-character-per-call change with no behavioral impact (both are generated alongside each other; same params, same response shape, same auth path) — it's a transport-compatibility fix, not an architectural decision.
- **Fix:** All four round-trip Python tests use `await ...asyncio_detailed(...)` instead of `.sync_detailed(...)`. The helper `_wire_asgi_transport` correspondingly calls `set_async_httpx_client` (not `set_httpx_client`) and constructs an `httpx.AsyncClient`. Inline docstring documents the constraint so future contributors don't trip over it.
- **Files modified:** backend/tests/test_sdks_round_trip.py
- **Verification:** All 4 Python round-trip tests pass.
- **Committed in:** `d6e97ed9` (Task 1)

**2. [Rule 1 — Bug] SDK's UNSET sentinel breaks JSON serialization on GET-with-optional-body endpoints**

- **Found during:** Task 1, first round-trip run after fix #1
- **Issue:** `search_datasets_endpoint_search_datasets_get._get_kwargs` unconditionally sets `_kwargs["json"] = body` regardless of body type — both branches of the `if isinstance(body, list)` check assign the same value. When body defaults to the SDK's `UNSET` (an `Unset` instance), httpx tries to JSON-serialize it and raises `TypeError: Object of type Unset is not JSON serializable`. This is a known openapi-python-client 0.28.3 quirk for endpoints declaring optional list bodies on GET routes.
- **Why Rule 1 (not Rule 4):** It's a generator behavior we have to work around, not an architectural problem. The fix is one line per call site (passing `body=None`); the alternative — patching the generator's templates — is out of scope.
- **Fix:** All test calls to the search endpoint pass `body=None` explicitly. Inline comment documents the workaround so consumers (Phase 216 CLI) inherit the pattern.
- **Files modified:** backend/tests/test_sdks_round_trip.py (search and api_key auth tests)
- **Verification:** Search endpoint round-trips with 200 OK; api-key-auth round-trips with 200 OK.
- **Committed in:** `d6e97ed9` (Task 1)

**3. [Rule 3 — Blocking] subprocess.run inside async test deadlocks against the in-test uvicorn**

- **Found during:** Task 1, first run of the TypeScript subprocess test
- **Issue:** The test spawns a uvicorn server on the same event loop as the pytest test (via `asyncio.create_task(server.serve())`). When the test then calls `subprocess.run(...)` synchronously, it blocks the calling thread → blocks the event loop → uvicorn can't process the HTTP requests the Node subprocess is making → Node hangs → subprocess.run waits 30s → `subprocess.TimeoutExpired`.
- **Why Rule 3:** Without this fix, the TS round-trip test can never pass. The fix is mechanical — wrap the blocking call in `asyncio.to_thread` so the loop keeps serving while the subprocess waits in a worker thread.
- **Fix:** `result = await asyncio.to_thread(subprocess.run, [node, str(ts_test)], env=env, ...)` instead of bare `subprocess.run(...)`. Inline comment documents the rationale.
- **Files modified:** backend/tests/test_sdks_round_trip.py
- **Verification:** TS subprocess test passes in <8s including server start/stop.
- **Committed in:** `d6e97ed9` (Task 1)

---

**Total deviations:** 3 auto-fixed (1 Rule 1, 2 Rule 3)
**Impact on plan:** No scope creep. All three fixes were necessary to satisfy must-haves; all are documented inline so future contributors and Plan 05's docs can pick them up; no new files, no new dependencies.

## Empirical Findings

- **Pitfall 5 confirmation (operationIds):** The actual generator output uses single-underscore separators, NOT the double-underscore prose paths from the original ROADMAP. Confirmed module names: `search_datasets_endpoint_search_datasets_get`, `get_single_dataset_datasets_dataset_id_get`, `upload_file_ingest_upload_post`. Note the upload endpoint lives under `geolens_sdk.api.datasets` (not `.api.ingest`) — the generator buckets by FastAPI tag, and `/ingest/upload` is tagged "datasets".

- **Pitfall 4 closure (X-API-Key not in OpenAPI spec):** The `test_api_key_auth_mode` test creates an API key via `POST /auth/api-keys/` (admin permissions inherited from the seeded admin user), then constructs `GeolensClient(base_url=..., api_key=api_key)` and calls `/search/datasets/`. Status 200 confirms the wrapper's `X-API-Key` header is honored by the backend's `_resolve_api_key()` precedence chain, despite `X-API-Key` not being declared in the OpenAPI security schemes (only `OAuth2PasswordBearer` is).

- **Pitfall 8 confirmation (httpx.ASGITransport + set_*_httpx_client):** Confirmed that the AuthenticatedClient's `set_async_httpx_client` bypasses the lazy header injection in `get_async_httpx_client`. The wiring helper `_wire_asgi_transport` therefore reads `auth_header_name`/`prefix`/`token` off the underlying client and constructs the `httpx.AsyncClient` with auth headers up front. Documented in the helper's docstring.

- **Assumption A2 (ASGITransport with the generator's client):** Verified — works for the async path. Sync path requires switching to `asyncio_detailed`. Both halves of the assumption confirmed empirically.

- **Assumption A3 (Node subprocess from pytest):** Verified — the skip-with-reason path fires correctly when `node` or `dist/index.js` are absent. When both are present, the test passes in ~5s end-to-end. The deadlock issue (Deviation 3) is a genuine constraint not documented in the assumption — adding it to the Plan 05 docs note.

- **TS function names verified against compiled dist:** `searchDatasetsEndpointSearchDatasetsGet`, `getSingleDatasetDatasetsDatasetIdGet`, `uploadFileIngestUploadPost` — confirmed by inspecting `sdks/typescript/dist/client/sdk.gen.d.ts` declared exports. Path-parameter convention is `path: { dataset_id: ... }` (per @hey-api/openapi-ts 0.96.1).

## Issues Encountered

- **Plan 03 SUMMARY claims `from geolens_sdk import GeolensClient` works, but the file `__init__.py` only exports `AuthenticatedClient` and `Client`.** Root cause: the Plan 02 Makefile cp-stash list does not include `__init__.py`, so `--overwrite` resets it to the bare generator default on every regen. Plan 04's tests work around this by importing from the explicit submodule path (`from geolens_sdk.auth import GeolensClient`). This is fine for Plan 04's must-haves but should be addressed by Plan 05 (or a follow-up): adding `__init__.py` to the cp-stash and `:!` exemption lists in the Makefile, with the file content authored to re-export `GeolensClient`. Logging here so the gap is visible without re-running the surface scan.

- **Pre-existing pydantic v2.0 deprecation warnings.** Many `tests/...` runs surface ~15 `PydanticDeprecatedSince20` warnings about `Field(example=...)` usage in backend schemas. Out of scope for Plan 04 — these are pre-existing and would surface for any test invocation. Logged as background noise; not added to deferred-items.

- **`node` not available in CI.** The current ci.yml has `setup-node@v6` only on jobs that need it (frontend, sdks-check). The new `backend-test` job does NOT install Node. So when CI runs `pytest tests/test_sdks_round_trip.py` as part of `backend-test`'s test suite, the TS subprocess test will skip-with-reason ("node not available on this runner"). For full TS round-trip verification, either (a) extend backend-test to install Node + build the TS SDK, or (b) accept that the sdks-check job is the one that exercises the regeneration drift, while the round-trip test serves as a local-dev signal. Plan 05's docs/sdks.md should clarify the test matrix; this is not a blocker for v13.1 SC.

## User Setup Required

- **For first SDK publish (whenever the user is ready):**
  - Create PyPI account + project token; add as repo secret `PYPI_TOKEN`.
  - Create npm account + claim the `@geolens` org; create automation token with publish scope; add as repo secret `NPM_TOKEN`.
  - Trigger `Publish SDKs` workflow from GitHub Actions UI: select target (python / typescript / both) and dry_run (recommended for first run).
  - First publish succeeds → switch dry_run off → real publish.
  - Documented end-to-end in Plan 05's `docs/sdks.md` (forthcoming).

- **No setup required for routine development work.** The `sdks-check` job runs automatically on every PR. The round-trip test runs in `backend-test` (Python half) and locally (TS half — Node + uvicorn).

## Next Phase Readiness

**Ready for Plan 05 (docs/sdks.md):**

- Round-trip test layout is stable; Plan 05 should document:
  - The `from geolens_sdk.auth import GeolensClient` import path AND the `__init__.py` gap (add to cp-stash list as a Plan 05 sub-task or follow-up issue).
  - The `body=None` workaround for optional list bodies on GET routes.
  - The asyncio_detailed-only path for in-process testing (ASGITransport).
  - The `npm publish --access public` flag requirement on first publish.
  - The PYPI_TOKEN / NPM_TOKEN secrets configuration step.
  - The dry_run input on the publish workflow as a safe verification.

- The CI gate is active. Plan 05's verification step can include "the new sdks-check job runs green on the v13.1 PR" as part of its acceptance criteria.

- Phase 215's three SCs at the integration-test level are all closed:
  - **SC#1 (Python round-trip):** 4 tests passing locally, runs in `backend-test` CI job.
  - **SC#2 (TypeScript round-trip):** 1 test passing locally; in CI it'll skip until backend-test is extended with Node setup, but the TS regeneration drift is fully covered by sdks-check.
  - **SC#3 (CI drift gate):** sdks-check job in place, `make sdks-check` exits 0 on the current tree.

**Ready for Phase 216 (CLI MVP):**

- The Python SDK's auth wrapper, generated client, and round-trip test all proven against live HTTP. Phase 216's CLI can `import GeolensClient` (from the explicit module path) and rely on the same patterns surfaced here (asyncio_detailed for in-process tests, `body=None` for optional GET bodies, `.client` property as the bridge to generated SDK functions).

**No blockers** for Plan 05 or Phase 216.

## Threat Flags

None — no new attack surface introduced beyond the threat-register items already documented in PLAN-04, all of which are mitigated as designed:

- **T-215-04-01 (Token leaked in CI logs):** mitigated. `secrets.*` references are auto-masked by GitHub Actions; no token is interpolated in `run:` shell commands.
- **T-215-04-02 (Drift gate bypass):** mitigated. `sdks-check` runs on `backend == 'true' || github.event_name == 'push'` — same shape as openapi-snapshot.
- **T-215-04-03 (Spoofing — compromised registry account):** mitigated. `workflow_dispatch` requires repo-write permission to trigger; per-package tokens limit blast radius.
- **T-215-04-04 (npm publishConfig.access drift):** mitigated. Belt-and-suspenders — `--access public` flag in the workflow + `publishConfig.access: public` in package.json.
- **T-215-04-05 (Test JWT exposure in CI logs):** mitigated. The admin JWT used in tests is signed with the test-only `JWT_SECRET_KEY` and has no value outside the ephemeral CI environment.
- **T-215-04-06 (Test failure not actionable):** mitigated. The TS subprocess assertion includes both `result.stdout` and `result.stderr` in the failure message; skip-with-reason path gives clear remediation messages.
- **T-215-04-07 (CI time consumption):** mitigated. Python half ~3s, TS half ~5s, total round-trip suite well under 10s. `subprocess.run(timeout=30)` ceiling caps runaway.
- **T-215-04-08 (npm ci ignoring lockfile):** accept (as planned). `npm ci` errors out on lockfile mismatch, which is the desired fail-loud behavior.

## Self-Check: PASSED

- `backend/tests/test_sdks_round_trip.py` — FOUND (377 LOC, contains `class TestPythonAuthWrapperUnit`, `def test_search_datasets`, `def test_api_key_auth_mode`, `ASGITransport`, `X-API-Key`)
- `sdks/typescript/test/round_trip.test.mjs` — FOUND (95 LOC, contains `createGeolensClient`, `GEOLENS_BASE_URL`)
- `.github/workflows/publish-sdks.yml` — FOUND (95 LOC, contains `name: Publish SDKs`, `workflow_dispatch:`, `UV_PUBLISH_TOKEN`, `NPM_TOKEN`, `npm publish --access public`)
- `.github/workflows/ci.yml` — MODIFIED (contains `sdks-check:`, `name: SDKs Drift Gate`, `run: make sdks-check`, `cache-dependency-path: sdks/typescript/package-lock.json`)
- Commit `d6e97ed9` (Task 1, test commit) — FOUND
- Commit `38f9fdb2` (Task 2, ci commit) — FOUND
- 12/12 tests pass: `pytest tests/test_sdks_round_trip.py -v` exit 0
- `make sdks-check` exit 0 — VERIFIED
- Both YAML files parse via `yaml.safe_load` — VERIFIED
- All planned acceptance-criteria greps pass on the committed files

---
*Phase: 215-sdks-from-openapi*
*Completed: 2026-04-27*
