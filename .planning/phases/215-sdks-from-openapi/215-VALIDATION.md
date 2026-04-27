---
phase: 215
slug: sdks-from-openapi
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-27
---

# Phase 215 — Validation Strategy

> Sourced from `215-RESEARCH.md` § Validation Architecture.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (anyio + asyncio) — already configured |
| Config file | `backend/pyproject.toml` |
| Quick run | `cd backend && PYTHONPATH=. uv run pytest tests/test_sdks_round_trip.py -v` |
| Full suite | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` |
| Build smoke | `cd sdks/python && uv build` ; `cd sdks/typescript && npm pack --dry-run` |
| Drift gate | `make sdks-check` (regenerates + git diff --exit-code; mirrors `make openapi-check`) |
| Round-trip | `make sdks-test` against in-process httpx ASGI transport |

## Sampling Rate

- **Per task commit:** `make sdks-check` (~30-60s)
- **Per wave merge:** `make sdks-test` + full backend pytest (~6min)
- **Phase gate:** All of: `make sdks` idempotent, `make sdks-check` clean, `make sdks-test` green, `uv build` + `npm pack` succeed, `docs/sdks.md` exists with both generator names, `actionlint .github/workflows/publish-sdks.yml` clean

## Per-Task Verification Map

| Task | Plan | Wave | Requirement | Test Type | Automated Command |
|------|------|------|-------------|-----------|-------------------|
| 215-01-01 | 01 | 1 | OCSDK-01,02 | smoke | `test -d sdks/python && test -d sdks/typescript && test -f sdks/python/.openapi-python-client.yaml && test -f sdks/typescript/openapi-ts.config.ts` |
| 215-02-01 | 02 | 2 | OCSDK-03 | smoke | `make sdks && git status -s sdks/` (zero diff after rerun = idempotent) |
| 215-02-02 | 02 | 2 | OCSDK-04 | unit | version-pin assertion script (see §Phase Requirements above) |
| 215-03-01 | 03 | 3 | OCSDK-01 | unit | `python -c "from geolens_sdk import GeolensClient; c = GeolensClient(base_url='', bearer_token='x'); assert c"` |
| 215-03-02 | 03 | 3 | OCSDK-02 | unit | `cd sdks/typescript && npm run build && node -e "const {createGeolensClient} = require('./dist'); console.log(createGeolensClient({baseUrl:'',bearerToken:'x'}))"` |
| 215-04-01 | 04 | 4 | OCSDK-01,02 | integration | `cd backend && uv run pytest tests/test_sdks_round_trip.py -v` |
| 215-04-02 | 04 | 4 | OCSDK-03 | CI | new `sdks-check` job in `.github/workflows/ci.yml` (or equivalent); `actionlint` clean |
| 215-04-03 | 04 | 4 | OCSDK-04 | docs | `test -f docs/sdks.md && grep -qE "openapi-python-client.*hey-api/openapi-ts" docs/sdks.md` |
| 215-05-01 | 05 | 5 | All | gate | full pytest passes (≥1988 floor); SC#1-#4 verified |

## Wave 0 Requirements

- [ ] `sdks/python/` and `sdks/typescript/` directories scaffolded
- [ ] Generator config files (`.openapi-python-client.yaml`, `openapi-ts.config.ts`)
- [ ] `sdks/python/pyproject.toml` and `sdks/typescript/package.json` initial scaffolds
- [ ] `scripts/sync_sdk_versions.py` (NEW) — pins SDK version to backend OpenAPI version
- [ ] `Makefile` extensions: `sdks`, `sdks-check`, `sdks-test`, `publish-sdks-py`, `publish-sdks-ts` targets
- [ ] `backend/tests/test_sdks_round_trip.py` (NEW) — pytest module
- [ ] `.github/workflows/publish-sdks.yml` (NEW) — manual-trigger publish workflow scaffold
- [ ] `docs/sdks.md` (NEW)

## Manual-Only Verifications

| Behavior | Why Manual | Test Instructions |
|----------|------------|-------------------|
| `pip install geolens-sdk` succeeds | Requires actual PyPI publish (out of scope per CONTEXT.md `<deferred>`) | After Phase 215 ships, user creates PyPI account + token, manually triggers `publish-sdks.yml` workflow |
| `npm install @geolens/sdk` succeeds | Requires actual npm publish + `@geolens` org claim | Same as above; user claims `@geolens` npm org first |

## Validation Sign-Off

- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes)

**Approval:** pending (auto-mode)
