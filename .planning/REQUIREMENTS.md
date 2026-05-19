# Requirements: GeoLens v1012 New-User Hardening + Reupload

**Defined:** 2026-05-19
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Make the literal new-user install and first-hour exploration of GeoLens work end-to-end with no rough edges. Close the 17 still-open M001-7n8vpc audit findings + 6 enhancements (EW-01..06) and ship the missing Reupload affordance (IMPORT-04).

**Source:** `.planning/M001-7n8vpc-dry-run-audit.md` (gitignored, 815 lines) — orchestrator-driven new-user dry-run audit ran 2026-05-19. 3 Critical fixes already shipped on `main` (BU-01 `7b168bde`, BU-02 `b4ad03d9`, SEED-01 `787f4e43`) and folded into `[1.2.0]` CHANGELOG via `89f37cca`. This milestone bundles the cleanup that ships AFTER v1.2.0, tagged v1.3.0.

**Public tag:** v1.3.0 (minor bump — IMPORT-04 is feature work, follows v1.2.0 precedent of "minor when features ship").

**Cross-repo:** DOC-* and EW-01/02 requirements track here for traceability; the actual docs PRs land in `~/Code/getgeolens.com/.planning/`.

## v1 Requirements

### Documentation (Quickstart Hardening, Cross-Repo with getgeolens.com)

- [ ] **DOC-01**: Quickstart at `docs.getgeolens.com/guides/quickstart/` documents the API-seeder path (`seed-natural-earth.py` + `seed-ago-data.py`) so new users can populate the catalog without discovering scripts independently. (Merges audit DOC-01 + EW-02 — same fix, two angles.)
- [ ] **DOC-02**: `seed-ago-data.py` is usable from the quickstart path — either accept `--username/--password` like `seed-natural-earth.py`, OR document the "create your first API key" workflow inline with the seeder docs.
- [ ] **DOC-03**: Quickstart prerequisites list "Python 3.10+ with `httpx`" (scoped to the seeders section).
- [ ] **DOC-04**: Quickstart's "1-2 minutes" startup-time claim is replaced with a measured/range expectation that survives variance (or the claim is removed in favor of `install.sh` wait-for-health output).
- [ ] **DOC-05**: Quickstart documents the interactive credential prompt that `install.sh` raises (and/or the `GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD` env-var alternative).

### Bring-Up

- [ ] **BU-03**: Apple Silicon `linux/amd64` platform-mismatch warning emitted by `docker compose up` is either suppressed (via `platform:` declarations) or documented as expected/harmless in the quickstart.

### Seeders

- [ ] **SEED-02**: `seed-ago-data.py` survives ogr2ogr timeouts on large AGO layers — configurable timeout (env or CLI flag) and/or per-layer retry with partial-progress reporting; defaults are raised above 120s for layers known to be large.
- [ ] **SEED-03**: Upstream AGO data-quality noise (malformed feature responses, missing columns) is summarized cleanly rather than dumped verbatim line-by-line.
- [ ] **SEED-04**: `ogr2ogr` failure output omits the full driver list — user sees only the actionable error message.

### UX

- [ ] **UX-01**: API Keys workflow is reachable from login within 1-2 clicks via primary admin nav, OR is signposted from the seeder docs so new users running `seed-ago-data.py` know exactly where to mint a key. (Discovery requirement, not a UI relocation requirement.)

### Console Hygiene

- [ ] **CONSOLE-01**: Anonymous Search page (`/`) and anonymous `/login` fire ZERO 401-error console noise — close the partial regression of v1010.2 SF-06 by gating any remaining authed-endpoint hooks (`/api/auth/refresh/` ×2, `/api/auth/me/` ×2, `/api/auth/me/permissions/` ×3, `/api/admin/ai-status/` ×3, etc.).

### Routes

- [ ] **ROUTE-01**: `/admin/saml` renders an "Enterprise Feature" placeholder/notice page in community edition (with brief explainer + docs link), instead of silently redirecting to `/admin/overview` with no signal.
- [ ] **ROUTE-02**: 404 page (`NotFoundPage`) sets a proper `<title>` (e.g. "Page not found · GeoLens") instead of inheriting the default app title.
- [ ] **ROUTE-03**: `/register` for already-authenticated users redirects to `/` with a visible info banner/toast ("Already signed in — redirected to home") instead of silently redirecting with no UI feedback.
- [ ] **ROUTE-04**: `/m/{invalid-share-token}` renders a clean 404 / "Map not found" view without leaking the underlying API 404 to the browser console.

### Import Operations

- [ ] **IMPORT-02**: Choose File button in the Upload File tab dropzone is fully clickable — the decorative `<span class="absolute -inset-1.5 rounded-[20px] border border-dashed border-primary/40">` no longer intercepts pointer events. (Likely `pointer-events: none` on the decorative span.)
- [ ] **IMPORT-03**: Upload File commit produces zero React `setState during render` warnings — root-cause the offending `setState` call and route it through `useEffect` or `queueMicrotask` per React 19 rules.
- [ ] **IMPORT-04**: User can re-upload / replace a dataset's source file from the dataset detail page — new UI affordance (button on dataset detail page) + backend re-import flow that preserves dataset ID/slug, regenerates derivatives (tiles, thumbnail, embeddings if applicable), and writes an audit-log entry. *(NEW FEATURE — drives the v1.3.0 minor bump.)*
- [ ] **IMPORT-05**: Register Table empty state reframes the "no tables found" message — when all PostGIS tables are already registered as datasets, the empty state shows "All tables are registered" (success framing) rather than absence framing. (Merges audit IMPORT-05 + EW-06 — same fix.)

### Easy Wins

- [ ] **EW-01**: Documented bring-up uses a single `docker-compose.yml` path — `docker-compose.demo.yml` is consolidated into the main compose (with profile-gated demo seeders) OR clearly labeled in docs as an optional convenience that the quickstart no longer steers users toward. The new-user quickstart path is single-file.
- [x] **EW-04**: `.env.example` includes a documented `DATABASE_SSL_MODE` line with a comment explaining `prefer` vs `disable` vs `require` for local-dev vs containerized PG vs managed PG. (Defense-in-depth against BU-01 regression.)
- [ ] **EW-05**: STAC import wizard stages selection and confirms total download size before committing to GB-scale fetches — user sees expected total bytes + per-item count before clicking "Import N items".

### Close Gate

- [ ] **CTRL-01**: All v1012 requirements verified via smoke gates (typecheck 0 / vitest green / `e2e:smoke:builder` green / i18n parity 4/4 locales) + live verification on a fresh `localhost:8080` stack against the new-user flow (login → search → import → register table → seed catalog → dataset detail). CHANGELOG `[Unreleased]` block populated. Local `v1.3.0` tag created. (If Playwright MCP is available at close time, prefer live MCP re-verify; otherwise rely on headless `e2e:smoke` + manual browser-console check.)

## v2 Requirements

Deferred to future release. Tracked but not in this milestone.

### BasemapSublayerEditorScene Full Styling

- **BASEMAP-SUBLAYER-01**: Full per-sublayer styling persistence — jsonb-additive `MapBasemapConfig.sublayer_overrides` + live MapLibre dispatch through `applyBasemapConfigToMap` with basemap-preset-aware sublayer style filtering. Path B FIX deferred from v1011.1 EMRG-FN-01 (Path A REMOVE shipped); 3-5 day feature phase; prioritize only if/when basemap-sublayer styling becomes a real user need.

### Marketplace & Distribution

- **MARKETPLACE-01**: v1.7 Marketplace & Distribution unpause — Phases 36-42 paused at Phase 40 (AWS AMI Build).

### Enterprise Backlog

- **ENT-999.13**: Persistent connector registry (Enterprise tier; scheduled mirroring + encrypted credential vault).
- **ENT-999.14**: Helm chart + AMI Packer pipeline (deployment artifacts).
- **ENT-999.15**: SBOM + signed image distribution.
- **ENT-999.16**: Extract `geolens-schemas` PyPI package.

### Cloud Tier Prerequisites

- **CLOUD-999.6**: Tenant scoping infrastructure for multi-tenant isolation (Cloud-tier blocker; single-tenant Enterprise unaffected).

## Out of Scope

Explicitly excluded for v1012. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| BasemapSublayerEditorScene Path B FIX | Deferred to v2 — 3-5 day feature phase, no current user demand. Path A REMOVE shipped in v1011.1. |
| v1.7 Marketplace & Distribution unpause | Distinct distribution milestone; not new-user / audit-cleanup shape. |
| Multi-tenant Cloud prerequisites (Phase 999.6) | Cloud-tier blocker, not new-user friction. |
| Enterprise backlog (999.13-16) | Enterprise-overlay scope, not core new-user / audit hygiene. |
| `seed-ago-data.py` rewrite to use the GeoLens SDK | DOC-02 only requires usability documentation OR a `--username/--password` minimal patch — full SDK migration is overkill. |
| New map authoring capabilities (live collaboration, time sliders, annotation layers) | Out of audit-cleanup shape. |
| Real-time chat / video posts / OAuth login | Not core to GeoLens. |
| DOC-06 Titiler host-port documentation | Architecture note in the audit, NOT a defect — Titiler is intentionally not host-exposed. |
| EW-03 install.sh wait-for-health | Already shipped at `b4ad03d9` (2026-05-19) — credit-only, not a v1012 requirement. |
| Recreate public repo before launch | Pre-existing pending todo from 2026-05-05; release-process work, not v1012 audit hygiene. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DOC-01 | Phase 1053 | Pending |
| DOC-02 | Phase 1053 | Pending |
| DOC-03 | Phase 1053 | Pending |
| DOC-04 | Phase 1053 | Pending |
| DOC-05 | Phase 1053 | Pending |
| BU-03 | Phase 1053 | Pending |
| EW-01 | Phase 1053 | Pending |
| EW-04 | Phase 1053 | Complete |
| SEED-02 | Phase 1054 | Pending |
| SEED-03 | Phase 1054 | Pending |
| SEED-04 | Phase 1054 | Pending |
| UX-01 | Phase 1054 | Pending |
| CONSOLE-01 | Phase 1054 | Pending |
| ROUTE-01 | Phase 1054 | Pending |
| ROUTE-02 | Phase 1054 | Pending |
| ROUTE-03 | Phase 1054 | Pending |
| ROUTE-04 | Phase 1054 | Pending |
| IMPORT-02 | Phase 1054 | Pending |
| IMPORT-03 | Phase 1054 | Pending |
| IMPORT-05 | Phase 1054 | Pending |
| EW-05 | Phase 1054 | Pending |
| IMPORT-04 | Phase 1055 | Pending |
| CTRL-01 | Phase 1056 | Pending |

**Coverage:**
- v1 requirements: 23 total
- Mapped to phases: 23
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-19*
*Last updated: 2026-05-19 — traceability table filled by roadmapper*
