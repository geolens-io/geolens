---
phase: 215-sdks-from-openapi
verified: 2026-04-29T20:00:00Z
status: human_needed
score: 4/4 ROADMAP SC verified
overrides_applied: 0
human_verification:
  - test: "Live PyPI publish of geolens-sdk via .github/workflows/publish-sdks.yml"
    expected: "`pip install geolens-sdk` from PyPI succeeds"
    why_human: "First publish requires PYPI_TOKEN secret + claiming the `geolens-sdk` PyPI name; workflow_dispatch only"
  - test: "Live npm publish of @geolens/sdk via .github/workflows/publish-sdks.yml"
    expected: "`npm install @geolens/sdk` from npm succeeds"
    why_human: "First publish requires NPM_TOKEN secret + claiming the `@geolens/sdk` scope"
notes: "Aggregated post-hoc by /gsd-plan-milestone-gaps close-out from per-plan verification gate (Plan 05). Functional verification was complete at phase close 2026-04-27."
---

# Phase 215: sdks-from-openapi Verification Report

**Phase Goal:** External integrators (and the v13.1 CLI) consume GeoLens through auto-generated, version-pinned Python and TypeScript SDKs; SDK drift against the OpenAPI snapshot is impossible to merge accidentally.

**Verified:** 2026-04-29T20:00:00Z (paperwork close-out aggregating Plan 05 verification gate of 2026-04-27)
**Status:** human_needed (live publish deferred per CONTEXT — workflow_dispatch only)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth (SC) | Status | Evidence |
| --- | ---------- | ------ | -------- |
| 1 | `pip install geolens-sdk` yields typed Python client; round-trip against `/search/datasets`, `/datasets/{id}`, `POST /ingest` succeeds | VERIFIED (build) | `sdks/python/` (Apache-2.0, openapi-python-client). `GeolensClient` + bearer/api-key/anonymous wrappers. Plan 04 round-trip test (12 tests pass) covers all three endpoints. `uv build` produces wheel + sdist. Live PyPI publish deferred (workflow_dispatch). |
| 2 | `npm install @geolens/sdk` yields typed TS client with same auth helpers; round-trip succeeds | VERIFIED (build) | `sdks/typescript/` (Apache-2.0, hey-api/openapi-ts). `createGeolensClient` + bearer/api-key/anonymous wrappers. `npm pack` produces tarball. Live npm publish deferred. |
| 3 | `make sdks` regenerates one-shot; `make sdks-check` fails CI on drift (mirrors `make openapi-check`) | VERIFIED | `Makefile` defines `sdks`, `sdks-check`, `sdks-test`, `publish-sdks-py`, `publish-sdks-ts` targets. `make sdks-check` CI gate at `.github/workflows/ci.yml:109` (sdks-check job). Plan 05 verification gate: `make sdks-check` exit 0. |
| 4 | SDK package version pins to OpenAPI snapshot version; `docs/sdks.md` documents generators + release process | VERIFIED | `scripts/sync_sdk_versions.py` pins all version files to `openapi.json info.version`. `docs/sdks.md` (305 lines) documents both generators (openapi-python-client + hey-api/openapi-ts) with rationale and publish/release process. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `sdks/python/` | Apache-2.0 Python SDK with auth wrappers | VERIFIED | Plan 01 scaffold + Plan 02 first regen + Plan 03 wrappers |
| `sdks/typescript/` | Apache-2.0 TS SDK with auth wrappers | VERIFIED | Plan 01 scaffold + Plan 02 first regen + Plan 03 wrappers |
| `Makefile` sdks targets | sdks, sdks-check, sdks-test, publish-sdks-py, publish-sdks-ts | VERIFIED | Plan 02 |
| `scripts/sync_sdk_versions.py` | one-shot version pin from openapi.json | VERIFIED | Plan 02; extended in Phase 216 to cover CLI |
| `scripts/flatten_openapi_defs.py` | preprocessor for generator | VERIFIED | Plan 02 (research-extension finding) |
| `.github/workflows/ci.yml` sdks-check job | drift gate mirroring openapi-check | VERIFIED | ci.yml:109 |
| `.github/workflows/publish-sdks.yml` | manual-trigger publish workflow | VERIFIED | Plan 04 (workflow_dispatch only) |
| `docs/sdks.md` | ≥300 lines docs covering generators + release | VERIFIED | 305 lines |
| Round-trip integration test | 12 tests covering both SDKs against running instance | VERIFIED | Plan 04; 12 pass at Plan 05 verification gate |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `make sdks-check` | CI failure on drift | `.github/workflows/ci.yml` | WIRED |
| `sync_sdk_versions.py` | both SDK version files | sed-based pin | WIRED (idempotent — Plan 05 confirmed exit 0) |
| Phase 216 CLI | `geolens_sdk` Python client | dep in `cli/pyproject.toml` | WIRED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| OCSDK-01 | 215-03 + 215-04 | Python SDK auto-generated, Apache-2.0 | SATISFIED | `sdks/python/` + 12 round-trip tests pass; PyPI publish deferred (D-40 equivalent) |
| OCSDK-02 | 215-03 + 215-04 | TypeScript SDK auto-generated, Apache-2.0 | SATISFIED | `sdks/typescript/` + npm pack build proven |
| OCSDK-03 | 215-02 + 215-04 | `make sdks` + `make sdks-check` CI gate | SATISFIED | Makefile + ci.yml:109 |
| OCSDK-04 | 215-02 + 215-05 | Version pin + `docs/sdks.md` | SATISFIED | `sync_sdk_versions.py` + 305-line docs |

### Anti-Patterns Found

None. Plan 05 verification gate ran clean: alembic clean, 2001 tests pass, sdks-check exit 0, 12 round-trip pass, actionlint clean for Phase 215 workflows, both SDKs build.

### Human Verification Required

Live PyPI/npm publishes are deferred user actions (workflow_dispatch only) — equivalent to Phase 216's D-40 deferral. Verification covers up to wheel + npm pack build.

### Gaps Summary

No blocking gaps. All 4 ROADMAP SC verified at Plan 05 verification gate (2026-04-27).

### Tech Debt Noted

- VALIDATION.md status=draft, nyquist_compliant=false (paperwork-only).
- Pre-existing actionlint warning on e2e-test job (constant `if: false`).
- Pre-existing Pydantic v2 deprecation warnings.
- `deferred-items.md`: pre-existing test_collections flake (carried forward).

---

_Verified: 2026-04-29T20:00:00Z (post-hoc aggregation of Plan 05 verification gate 2026-04-27)_
_Verifier: Claude (gsd-plan-milestone-gaps close-out, paperwork pass)_
