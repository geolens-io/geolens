---
phase: 215-sdks-from-openapi
plan: 03
subsystem: infra
tags: [openapi, sdk, python, typescript, auth, bearer-token, x-api-key, hand-written-wrapper, drift-gate]

# Dependency graph
requires:
  - phase: 215-02
    provides: generated `Client`/`AuthenticatedClient` classes in sdks/python/geolens_sdk/client.py with `token`/`prefix`/`auth_header_name` constructor args; generated `client` singleton in sdks/typescript/src/client/client.gen.ts with `setConfig({ baseUrl, headers })`; cp-stash + `:!` exemption pattern wired in Makefile for auth.py/auth.ts/index.ts; generated `src/client/index.ts` barrel re-exporting all sdk functions + types
provides:
  - sdks/python/geolens_sdk/auth.py — hand-written `GeolensClient` class wrapping the generated AuthenticatedClient/Client with bearer/api-key/anonymous modes; mutating helpers `set_bearer_token` / `set_api_key`; `client` property exposing the underlying generated client
  - sdks/typescript/src/auth.ts — hand-written `createGeolensClient` factory with `GeolensClientOptions`/`GeolensClient` interfaces; configures generated singleton via `client.setConfig({ baseUrl, headers })`; mutual-exclusion guard
  - sdks/typescript/src/index.ts — public package entry re-exporting `createGeolensClient` + types alongside the generated `./client/index.js` barrel
  - Empirical validation that cp-stash (Makefile lines 74-76, 86-88) preserves all three hand-written files across `make sdks` regeneration
  - Empirical validation that `:!` pathspec exemptions (Makefile lines 96-98) exclude all three from `make sdks-check` drift gate
  - tsconfig.json `lib` extended with `DOM.Iterable` so generated `URLSearchParams.entries()` iteration typechecks (Rule 3 blocking fix)
affects:
  - 215-04 (round-trip integration test imports `GeolensClient` from `geolens_sdk` and `createGeolensClient` from `@geolens/sdk` — both wrapper APIs are now stable)
  - 215-05 (docs/sdks.md must document the wrapper API, header semantics matching backend `_resolve_api_key()` precedence, and the no-query-param-fallback decision per D-11)
  - 216-future (Phase 216 CLI consumes the Python SDK exclusively via `GeolensClient` — never imports `Client`/`AuthenticatedClient` directly per OCCLI-06)

# Tech tracking
tech-stack:
  added:
    - hand-written auth wrapper layer atop generated SDK clients (Python class + TS factory function)
  patterns:
    - "Header-only authentication surface in SDK wrapper (D-11) — backend's `?api_key=` query-param fallback is intentionally not exposed; cleaner public API + reduced attack surface"
    - "Mutual-exclusion guard at constructor: ValueError (Python) / Error (TS) when both bearer_token and api_key supplied — prevents ambiguous-auth state at API boundary"
    - "Wrapper as type boundary: typed `GeolensClientOptions`/`GeolensClient` interfaces in TS; the wrapper does NOT subclass or override the generated client — only configures it via documented public APIs (RESEARCH §\"Don't Hand-Roll\")"
    - "Underlying client exposed via `.client` property/key so power users can drop down to the raw generated SDK functions when needed"

key-files:
  created:
    - sdks/python/geolens_sdk/auth.py
    - sdks/typescript/src/auth.ts
    - sdks/typescript/src/index.ts
    - .planning/phases/215-sdks-from-openapi/215-03-SUMMARY.md
  modified:
    - sdks/typescript/tsconfig.json (added DOM.Iterable to lib for URLSearchParams.entries() typechecking — Rule 3 blocking fix)

key-decisions:
  - "Implemented D-10: hand-written auth wrappers in both languages; not regenerated. AuthenticatedClient(token, prefix, auth_header_name) is the documented Python primitive; client.setConfig({ headers }) is the documented TS primitive. Wrappers stay thin — no business logic, no logging, no token persistence."
  - "Implemented D-11: header-only API key. Constructor sets `Authorization: Bearer <token>` for bearer_token, `X-API-Key: <key>` for api_key. Backend's query-param fallback (`?api_key=<key>`) — supported by `_resolve_api_key()` for browser/embed contexts — is deliberately NOT exposed by the SDK wrapper."
  - "Mutual-exclusion guard: passing both bearer_token AND api_key to the constructor raises ValueError (Python) / throws Error (TS). Prevents silent precedence ambiguity at the SDK boundary."
  - "TypeScript wrapper configures the generated singleton client via `client.setConfig({ baseUrl, headers })` rather than wrapping it. Means all generated SDK function calls (e.g., `searchDatasetsEndpointSearchDatasetsGet({ client: sdk.client })`) inherit auth headers automatically. Aligns with @hey-api/openapi-ts's intended usage."
  - "Public TS package entry `src/index.ts` re-exports both the hand-written auth surface AND the generated `./client/index.js` barrel. Consumers do `import { createGeolensClient, searchDatasetsEndpointSearchDatasetsGet } from '@geolens/sdk'` — single import path."
  - "Rule 3 blocking fix: tsconfig.json `lib` extended with `DOM.Iterable` so `URLSearchParams.entries()` in generated `queryKeySerializer.gen.ts` typechecks. Plan 02 committed the file but never invoked `npm run build`; Plan 03 surfaced the latent typing gap. Minimal change — single-token addition to the lib array."

patterns-established:
  - "Auth wrapper as `client.setConfig({ headers })` shim (TypeScript) — the @hey-api singleton is configured globally; users never instantiate clients themselves"
  - "Auth wrapper as `AuthenticatedClient(token=, prefix=, auth_header_name=)` keyword-arg pass-through (Python) — exactly the generator's documented auth primitive"
  - "Hand-written file lifecycle: created in plan → cp-stashed across every `make sdks` → restored after generators → tracked + committed via `git add -f` (since generated dirs may be partially gitignored at sub-tree level) → exempted from drift gate via `:!` pathspecs"
  - "Threat-model `print`/`console.log` audit on every wrapper file — catches token-leakage regressions at code-review time without needing runtime instrumentation"

requirements-completed:
  - OCSDK-01
  - OCSDK-02

# Metrics
duration: 3m 36s
completed: 2026-04-27
---

# Phase 215 Plan 03: Hand-written auth wrappers (Python GeolensClient + TS createGeolensClient) Summary

**Hand-maintained `GeolensClient` (Python) and `createGeolensClient` (TypeScript) wrappers around the generated SDK clients — both expose the same `bearer_token` / `api_key` / anonymous modes, raise on ambiguous-auth, configure the underlying client via documented public APIs, and survive `make sdks` regeneration via cp-stash + `:!` drift-gate exemptions verified end-to-end.**

## Performance

- **Duration:** 3m 36s
- **Started:** 2026-04-27T19:37:56Z
- **Completed:** 2026-04-27T19:41:32Z
- **Tasks:** 2
- **Files committed:** 3 created (auth.py, auth.ts, index.ts) + 1 modified (tsconfig.json) across two commits
- **Lines added:** 92 (auth.py) + 78 (auth.ts) + 16 (index.ts) = 186 LOC of hand-written wrapper code

## Accomplishments

- Python `GeolensClient(base_url, *, bearer_token=, api_key=)` works for all three auth modes; mutating `set_bearer_token` / `set_api_key` swap the underlying client; `.client` property gives access to the raw generated client for power users
- TypeScript `createGeolensClient({ baseUrl, bearerToken?, apiKey? })` configures the generated `@hey-api` singleton; returns `{ baseUrl, headers, client }` triple for inspection + downstream SDK function calls
- Both wrappers raise/throw on mutually-exclusive auth inputs (ValueError / Error)
- `npm run build` produces `dist/index.js` + `dist/index.d.ts` with `createGeolensClient` declaration exposed (publishable package shape)
- 7 Python behavior smoke tests pass; 4 TypeScript behavior smoke tests pass (bearer header, x-api-key header, anonymous, mutual-exclusion throw — all verified against compiled `dist`)
- `make sdks-check` exits 0 — cp-stash preserves all three hand-written files across regeneration; `:!` pathspec exemptions exclude them from the drift gate
- Threat-model T-215-03-01 mitigated: zero `print` / `console.log` calls in any wrapper file (confirmed by grep)
- OCSDK-01 (Python auth helpers) + OCSDK-02 (TS auth helpers) closed at the SDK code level; round-trip behavioral verification deferred to Plan 04

## Task Commits

Each task committed atomically:

1. **Task 1: Create Python auth wrapper (sdks/python/geolens_sdk/auth.py)** — `78a6aef8` (feat)
2. **Task 2: Create TypeScript auth wrapper + public entry + tsconfig lib fix (sdks/typescript/src/{auth.ts,index.ts}, sdks/typescript/tsconfig.json)** — `618d44c8` (feat)

**Plan metadata commit:** pending (final commit captures this SUMMARY.md + STATE.md + ROADMAP.md updates)

## Files Created/Modified

### Created

- `sdks/python/geolens_sdk/auth.py` — Hand-written `GeolensClient` class. Constructor accepts `base_url` + exactly one of `bearer_token` / `api_key`; raises ValueError if both. Bearer mode wraps `AuthenticatedClient(token=bearer_token)` (defaults `prefix="Bearer"`, `auth_header_name="Authorization"`). API-key mode wraps `AuthenticatedClient(token=api_key, prefix="", auth_header_name="X-API-Key")`. No-auth mode wraps the anonymous `Client(base_url=base_url)`. `set_bearer_token(token)` / `set_api_key(key)` replace `self._client`. `.client` property exposes the underlying generated client for use with `geolens_sdk.api.*` functions. Module exports `GeolensClient` only via `__all__`.

- `sdks/typescript/src/auth.ts` — Hand-written `createGeolensClient` factory + `GeolensClientOptions` (input) + `GeolensClient` (output) interfaces. Imports the generated singleton from `./client/client.gen.js` and configures it with `setConfig({ baseUrl, headers })`. Builds a `headers` record at call time: `Authorization: Bearer <token>` for bearerToken, `X-API-Key: <key>` for apiKey. Returns `{ baseUrl, headers, client }`. Throws `Error` if both bearerToken and apiKey are supplied.

- `sdks/typescript/src/index.ts` — Public package entry. Re-exports `createGeolensClient` + `GeolensClientOptions` + `GeolensClient` from `./auth.js`, plus the generated `./client/index.js` barrel (~213 SDK functions + ~385 types). Single import path for consumers: `import { createGeolensClient, searchDatasetsEndpointSearchDatasetsGet } from '@geolens/sdk'`.

- `.planning/phases/215-sdks-from-openapi/215-03-SUMMARY.md` — this file.

### Modified

- `sdks/typescript/tsconfig.json` — Added `DOM.Iterable` to the `lib` array. The generated `src/client/core/queryKeySerializer.gen.ts` calls `URLSearchParams.entries()` (and iterates the returned IterableIterator), which requires `DOM.Iterable` for typechecking under strict mode. Plan 02 committed the file but never ran `npm run build`; Plan 03's `npm run build` step in Task 2's verification flushed out the latent typing gap. The fix is minimal and a standard tsconfig hardening for any code path that touches `URLSearchParams` iteration.

## Decisions Made

See key-decisions in frontmatter. Highlights:

- **Header-only API-key surface (D-11) preserved.** The wrappers do NOT expose query-parameter API key support. Backend's `_resolve_api_key()` accepts `?api_key=<key>` for browser/embed contexts (the iframe + tile-fetch transformRequest path), but that's a presentation-layer concern for the frontend, not an SDK consumer concern. SDK consumers always have the option of stuffing tokens into headers — there's no scenario where they NEED query params.

- **Wrapper does NOT subclass the generated client.** The Python `GeolensClient` holds an `AuthenticatedClient` / `Client` instance via composition; it doesn't extend either class. Same for TS — the wrapper function returns a `{ baseUrl, headers, client }` object literal. Reason: the generated clients evolve with the OpenAPI snapshot (add new fields, change signatures); inheriting against an unstable surface would chain wrappers tightly to generator internals. Composition keeps the wrapper at arm's length.

- **The `set_bearer_token` / `set_api_key` mutators replace `_client` rather than mutating in place.** Reason: the generated `AuthenticatedClient` and `Client` are `attrs.@define` dataclasses — they're not designed to swap auth post-construction. Cleanest path is to construct a new client; the underlying `httpx.Client` is lazy-initialized so the cost is low.

- **TS wrapper imports from `./client/client.gen.js` (with `.js` extension)** — required by the project's `module: NodeNext` + `moduleResolution: NodeNext` tsconfig. Same constraint applies to `./auth.js` and `./client/index.js` re-exports. NodeNext requires explicit `.js` extensions on relative imports even in TypeScript source files (TypeScript 5+ resolves them to `.ts` at compile time, then emits `.js` paths in the dist).

## Deviations from Plan

The plan was executed largely as written for Task 1 (Python wrapper). Task 2 needed one Rule 3 blocking fix to tsconfig.json that wasn't in the plan's `files_modified`.

### Auto-fixed Issues

**1. [Rule 3 - Blocking] tsconfig.json missing DOM.Iterable lib for URLSearchParams iteration**

- **Found during:** Task 2, Step D (`npm run build`)
- **Issue:** `tsc` failed with three errors in the generated `src/client/core/queryKeySerializer.gen.ts` file: `Property 'entries' does not exist on type 'URLSearchParams'` (line 60), `Argument of type ... is not assignable to parameter of type '(a: unknown, b: unknown) => number'` (line 60), `Type 'unknown' must have a '[Symbol.iterator]()' method that returns an iterator` (line 63). The generated code calls `Array.from(params.entries()).sort(([a], [b]) => a.localeCompare(b))` and `for (const [key, value] of entries)`, both of which need `URLSearchParams.entries()` returning an `IterableIterator<[string, string]>` rather than the bare `URLSearchParams` Iterable that `lib: DOM` alone exposes.
- **Why blocking:** Plan 03's must-haves require `npm run build` to produce `dist/index.js` + `dist/index.d.ts`. Without this fix, the build fails outright; auth.ts can't be exercised from compiled output; the smoke tests can't run.
- **Why Rule 3 (not Rule 4 architectural):** Adding `DOM.Iterable` to a tsconfig `lib` array is a single-token addition that has zero behavioral impact at runtime — it only widens the type surface available to typechecking. No new dependency, no new build step, no architectural shift. This is the standard tsconfig setting for any TS project that iterates `URLSearchParams`/`Headers`/`FormData` (all DOM iterables). The Plan 02 SUMMARY confirms `npm run build` was never invoked there, so the gap was latent — Plan 03 is the first time the TS code is actually compiled, and the fix is necessary at first compile.
- **Fix:** Changed `"lib": ["ES2022", "DOM"]` to `"lib": ["ES2022", "DOM", "DOM.Iterable"]` in `sdks/typescript/tsconfig.json`. Rerun `npm run build` — succeeds with no errors.
- **Files modified:** sdks/typescript/tsconfig.json
- **Verification:** `npm run build` exit 0; `dist/index.js` + `dist/index.d.ts` produced; `dist/index.d.ts` contains `createGeolensClient` declaration; 4 TS behavior smoke tests pass against compiled dist; `make sdks-check` exit 0 (tsconfig.json is hand-maintained config NOT generated by the SDK pipeline, so it's outside the regen surface — modification is committed as part of Task 2 and the post-regen `git diff --exit-code` sees a clean tree).
- **Committed in:** `618d44c8` (Task 2 commit, alongside auth.ts + index.ts)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking)
**Impact on plan:** No scope creep. The fix was confined to a single tsconfig token, was necessary to satisfy the plan's `npm run build` must-have, and the commit message documents it explicitly. Plan's outcome shape preserved (auth wrappers ship as designed; build produces publishable package).

## Issues Encountered

- **First `make sdks-check` after committing only Task 1 surfaced "cp: Error 1 (ignored)" lines in the output.** Looked alarming but is intentional: the cp-stash restore step uses `-cp …/_geolens_auth.ts …` (with a leading `-` so make ignores failures), and on the run where auth.ts/index.ts didn't yet exist (Task 1 committed only the Python wrapper), the cp-stash step had nothing to restore. Make printed "Error 1 (ignored)" twice — non-fatal. After Task 2 commit, all three cp-stash steps find their stashed files and the restore succeeds silently.

- **`make sdks-check` failed exactly once between Task 1 and Task 2 commits** because the unstaged tsconfig.json change tripped `git diff --exit-code`. Resolved by completing Task 2's commit (which staged tsconfig.json + the new auth.ts + index.ts together). This is normal git-state hygiene, not a pipeline bug.

## User Setup Required

None — Plan 03 only adds hand-written wrapper code and a single tsconfig setting. No new tools, no new env vars, no new GitHub secrets. The next user-action gate is Plan 04+'s publish workflow (still requires user-managed `UV_PUBLISH_TOKEN` / `NPM_TOKEN`).

## Next Phase Readiness

**Ready for Plan 04 (round-trip integration test + CI wiring + publish workflow scaffold):**

- Python: `from geolens_sdk import GeolensClient` — Plan 04's round-trip test imports this and uses `GeolensClient(base_url=..., bearer_token=...)` to authenticate against the live test backend. Note: `__init__.py` re-exports `GeolensClient` for the bare-module import path.
- Python: round-trip test will exercise the 7 in-plan behaviors as `test_python_auth_wrapper_unit` block AND chain with live HTTP calls to `GET /search/datasets`, `GET /datasets/{id}`, `POST /ingest` (per CONTEXT D-14). The `.client` property is the bridge — pass it to any `geolens_sdk.api.*` function.
- TypeScript: `import { createGeolensClient } from '@geolens/sdk'` — Plan 04's TS round-trip test (spawned via pytest + node) imports this from the compiled dist. The package's `dist/index.d.ts` exposes `createGeolensClient` with full type signatures, so consumers get autocomplete + typecheck immediately.
- TypeScript: round-trip test calls `searchDatasetsEndpointSearchDatasetsGet({ client: sdk.client })` etc. — same pattern as the JSDoc example in `auth.ts`.
- Drift gate is GREEN end-to-end. Plan 04's CI workflow can `make sdks-check` confidently; the gate has been validated empirically against the committed Plan 03 baseline.

**Ready for Plan 05 (docs/sdks.md):**

- The wrapper API surface is small enough to document in <100 lines: 4 modes per language (bearer / api_key / anonymous / both → error), one factory per language, the header-precedence rule. Plan 05 should also document:
  - The cross-language naming difference: Python `bearer_token` vs TS `bearerToken` (pythonic snake_case vs JS camelCase — intentional; matches each language's conventions)
  - The `.client` property/key as the access path to the underlying generated client
  - The "no query-param API key" decision (D-11) and where to look in the backend if you need that fallback (the `?api_key=` query param works against the deployed instance — just not via the SDK)
  - The `from `@hey-api`'s perspective, our wrapper is a configuration of the singleton client, not a replacement of it. Power users can still call `client.setConfig(...)` directly if they need per-request overrides.

**No blockers** for downstream plans. Both wrapper APIs are finalized; Plan 04 is a strict consumer; Plan 05 is documentation-only.

## Threat Flags

None — no new attack surface introduced. All threat-register items from PLAN-03 are mitigated as designed:

- **T-215-03-01 (Information disclosure — token logged or echoed):** mitigated. `grep -E 'print\(|console\.log|console\.error|console\.warn' sdks/python/geolens_sdk/auth.py sdks/typescript/src/auth.ts sdks/typescript/src/index.ts` returns zero matches. Tokens flow into a header dict and stop there.
- **T-215-03-02 (Spoofing — both bearer and api_key passed):** mitigated. `GeolensClient.__init__` raises ValueError; `createGeolensClient` throws Error. Both verified by behavior tests in this plan.
- **T-215-03-03 (Tampering — hand-written wrapper deleted by --overwrite):** mitigated. Plan 02's cp-stash pattern (Makefile lines 74-76, 86-88) preserves auth.py + auth.ts + index.ts across `make sdks`. Validated empirically: `make sdks-check` (which calls `make sdks`) exits 0 against the Plan 03 baseline.
- **T-215-03-04 (Tampering — drift gate flags hand-written file):** mitigated. `:!sdks/python/geolens_sdk/auth.py`, `:!sdks/typescript/src/auth.ts`, `:!sdks/typescript/src/index.ts` exemptions in Makefile lines 96-98. Validated by `make sdks-check` exiting 0.
- **T-215-03-05 (Information disclosure — API-key sent over query param + header double-send):** accept. Wrapper uses headers ONLY (D-11); query-param fallback is not exposed by the SDK.
- **T-215-03-06 (Repudiation — wrapper bypasses generator's auth machinery, weakening type-safety):** accept. Wrapper IS the type boundary (typed `GeolensClientOptions` in TS, typed Python keyword args). It uses documented public APIs (`AuthenticatedClient(token=…, prefix=…, auth_header_name=…)` / `client.setConfig({ headers })`) without subclassing or overriding.

## Self-Check: PASSED

- `sdks/python/geolens_sdk/auth.py` — FOUND (92 LOC, contains `class GeolensClient`)
- `sdks/typescript/src/auth.ts` — FOUND (78 LOC, contains `export const createGeolensClient`)
- `sdks/typescript/src/index.ts` — FOUND (16 LOC, re-exports auth + client)
- `sdks/typescript/dist/index.js` — FOUND (after `npm run build`)
- `sdks/typescript/dist/index.d.ts` — FOUND (contains `createGeolensClient` declaration)
- `.planning/phases/215-sdks-from-openapi/215-03-SUMMARY.md` — FOUND
- Commit `78a6aef8` (Task 1) — FOUND
- Commit `618d44c8` (Task 2) — FOUND
- `make sdks-check` exit 0 — VERIFIED end-to-end

---
*Phase: 215-sdks-from-openapi*
*Completed: 2026-04-27*
