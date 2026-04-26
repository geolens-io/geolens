---
phase: 225
slug: api-reference
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-25
---

# Phase 225 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | bash assertions (`docs/scripts/verify-build.sh`) + `astro check` + `npm run build` |
| **Config file** | `getgeolens.com/docs/astro.config.mjs`, `getgeolens.com/docs/scripts/verify-build.sh` |
| **Quick run command** | `cd getgeolens.com/docs && npm run build` |
| **Full suite command** | `cd getgeolens.com/docs && bash scripts/check-token-sync.sh && npx astro check && npm run build && bash scripts/verify-build.sh` |
| **Estimated runtime** | ~60–120 seconds for full suite (Astro build dominates) |

---

## Sampling Rate

- **After every task commit:** Run `cd getgeolens.com/docs && npx astro check` (≤10s)
- **After every plan wave:** Run `npm run build && bash scripts/verify-build.sh`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD-01 | 01 | 1 | API-01 | — | Snapshot fetch script writes deterministic JSON to `src/content/openapi/geolens.json` | smoke | `cd docs && node scripts/fetch-openapi.mjs && test -s src/content/openapi/geolens.json` | ❌ W0 | ⬜ pending |
| TBD-02 | 02 | 2 | API-02 | — | `starlight-openapi@0.25.0` registered as Starlight plugin; tag pages render under `/operations/tags/` | build | `cd docs && npm run build && grep -r "operations/tags" dist/ \| head -1` | ❌ W0 | ⬜ pending |
| TBD-03 | 03 | 2 | API-03 | T-225-AUTH | Auth page documents `X-Api-Key` header (not `Authorization: Bearer <api_key>`) | grep | `grep -F "X-Api-Key" docs/src/content/docs/guides/api/auth.mdx` | ❌ W0 | ⬜ pending |
| TBD-04 | 04 | 2 | API-04 | — | OGC page lists Common, Records, Features, STAC, Tiles with verified paths | grep | `grep -E "^## (OGC API|STAC|Tile)" docs/src/content/docs/guides/api/ogc.mdx \| wc -l` returns ≥5 | ❌ W0 | ⬜ pending |
| TBD-05 | 05 | 2 | API-05 | — | `src/content/openapi/README.md` documents fetch-openapi workflow + cadence | grep | `test -f docs/src/content/openapi/README.md && grep -F "fetch-openapi" docs/src/content/openapi/README.md` | ❌ W0 | ⬜ pending |
| TBD-06 | 06 | 3 | CI-01 | — | `starlight-links-validator` registered with `exclude` allowlist for forward-refs; build fails on broken internal links | build | `cd docs && npm run build` (passes) + intentional broken-link check (returns non-zero) | ❌ W0 | ⬜ pending |
| TBD-07 | 07 | 3 | API-02 (success #4) | — | Pagefind exclusion: `data-pagefind-body` absent on `/operations/tags/*` rendered HTML; present on `/guides/api/auth` and `/guides/api/ogc` | grep | `grep -L "data-pagefind-body" dist/guides/api/operations/tags/*/index.html` AND `grep -l "data-pagefind-body" dist/guides/api/auth/index.html` | ❌ W0 | ⬜ pending |
| TBD-08 | 07 | 3 | CI-01 | — | `verify-build.sh` extended with snapshot-presence + Pagefind-exclusion assertions | build | `bash docs/scripts/verify-build.sh` (exits 0 on green build, non-zero on missing snapshot or wrong pagefind state) | ❌ W0 | ⬜ pending |

*Plan IDs are placeholders until planner emits final plan numbers.*
*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `getgeolens.com/docs/scripts/fetch-openapi.mjs` — fetch script (API-01)
- [ ] `getgeolens.com/docs/src/content/openapi/geolens.json` — committed snapshot (API-01)
- [ ] `getgeolens.com/docs/src/content/openapi/README.md` — refresh-cadence doc (API-05)
- [ ] `starlight-openapi@0.25.0` + `starlight-links-validator@0.23.x` installed in `docs/package.json`
- [ ] `astro.config.mjs` updated with both plugins (correct registration order)
- [ ] `getgeolens.com/docs/src/content/docs/guides/api/index.mdx` — curated landing page (replaces Phase 224 placeholder)
- [ ] `getgeolens.com/docs/src/content/docs/guides/api/auth.mdx` — auth page (API-03), `X-Api-Key` header correct
- [ ] `getgeolens.com/docs/src/content/docs/guides/api/ogc.mdx` — OGC landing page (API-04)
- [ ] `getgeolens.com/docs/src/content/docs/_routeMiddleware.ts` — route middleware setting `entry.data.pagefind = false` for `/guides/api/operations/tags/*` paths
- [ ] `getgeolens.com/docs/scripts/verify-build.sh` — snapshot + pagefind assertions

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Operator workflow: `cd backend && docker compose up api` → `cd ../getgeolens.com/docs && npm run fetch-openapi` produces a non-empty diff if the spec changed | API-01, API-05 | Requires a running geolens API instance and is by design a manual cadence (per-release) | Spin up backend; run `npm run fetch-openapi`; verify `git diff src/content/openapi/geolens.json` shows expected changes |
| Auth page curl examples actually work against a live geolens instance | API-03 | Requires real JWT + API key + OAuth setup; test environment dependent | Issue test JWT via `/api/auth/login`; copy curl examples from rendered page; replace placeholder host; confirm 200 response |
| OGC page QGIS / GDAL / pystac-client examples produce expected outputs | API-04 | Requires installed QGIS, GDAL, and pystac-client; user environment dependent | Open QGIS → Add Layer → WFS → paste example URL → verify dataset list loads. Run `ogr2ogr` example → verify GPKG output. Run `pystac-client.Client.open(...)` → verify search results. |
| `data-pagefind-body` exclusion verified on rendered HTML | Success Criteria #4 | DOM-level assertion needs the build artifact; `verify-build.sh` automates this but a one-time manual confirmation prevents tooling drift | After `npm run build`, open `dist/guides/api/operations/tags/<some-tag>/index.html`, search for `data-pagefind-body` (must NOT exist on `<main>`); open `dist/guides/api/auth/index.html`, search for `data-pagefind-body` (MUST exist on `<main>`) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
