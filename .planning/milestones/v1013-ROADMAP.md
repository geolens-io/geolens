# v1013 Ingest Hardening — Milestone Archive

**Shipped:** 2026-05-20
**Public Tag:** v1.3.0 (local, push via `git push origin v1013 v1.3.0`)
**Local Tag:** v1013
**Phases:** 1057-1060 (4 phases, 15 plans)
**Requirements:** 10/10 satisfied
**Commit Range:** `7262bdea` (v1012 archive) → `9a8487f1` (v1013 audit) — 95 commits

## Goal

Close the 7 findings from the post-v1012 live smoke (2026-05-19) + the v1011.1-deferred BSE-01 styling persistence. Mix of P0 ingest reliability fixes (WFS-04, GPKG-01) and feature work (BSE-01 sublayer editor restoration with real persistence path).

## Phases Shipped

### Phase 1057: Service URL Reliability (shipped 2026-05-19, 3 plans)

**Goal:** Fix WFS abstract-geometry-type commit failure (P0), short-circuit probe orchestrator on first success, parse URI-form CRS references, fall back to VEC when probe response lacks geometry_type.

**Requirements satisfied:** WFS-04 (P0), PROBE-05 (P1), CRS-06 (P2), CLASS-07 (P2)

**Key commits:**
- `c6f13906` — `-nlt PROMOTE_TO_MULTI` → `-nlt GEOMETRY` on service ingest path (WFS-04 layer 1)
- `86b47544` — Wire `parse_crs_uri` into `extract_srid_from_json` as third fallback (CRS-06)
- `41e2c617` — Mirror `kind` field in frontend LayerInfo + consume `layer.kind` in ServiceUrlForm (CLASS-07)
- Lazy-enrich at preview time, not probe (PROBE-05 — was 63s, now ~1.3s)

### Phase 1058: Multi-Layer GPKG Handling (shipped 2026-05-19, 4 plans)

**Goal:** Add layer-select step to Reupload File path mirroring Service URL flow (P0 silent-data-swap fix), surface chosen layer name + schema diff in preview, enable multi-commit / ingest-all-layers path in Bulk Review.

**Requirements satisfied:** GPKG-01 (P0), GPKG-02 (P1), GPKG-03 (P2)

**Key surfaces:**
- `ReuploadDialog.tsx:581` — `selecting-file-layer` step with source_layer pre-selection
- `data-testid="schema-change-advisory"` banner in preview pane
- `POST /ingest/commit-fan-out/{job_id}` — N-layer fan-out endpoint (close-gate fixes 3 bugs)

### Phase 1059: Basemap Sublayer Editor (Path B FIX) (shipped 2026-05-20, 4 plans)

**Goal:** Restore per-sublayer styling surface removed in v1011.1 EMRG-FN-01 with a real persistence path through `MapBasemapConfig.sublayer_overrides` jsonb-additive; 3-5 day feature phase.

**Requirements satisfied:** BSE-01 (Feature)

**Key surfaces:**
- `MapBasemapConfig.sublayer_overrides` jsonb-additive field (zero Alembic migration)
- `applySublayerOverrides(map, overrides)` shared helper with idle-retry recovery
- `BasemapSublayerEditorScene.tsx` restored: STROKE / CASING / ZOOM RANGE / OPACITY / RESET sections
- 12 new vitest tests + de/es/fr i18n parity (9 new keys per locale)

### Phase 1060: Close Gate (shipped 2026-05-20, 4 plans)

**Goal:** Verify all 10 v1013 requirements through smoke gates + live Playwright MCP re-verify; delete 3 fixture datasets; populate CHANGELOG; cut v1013 + v1.3.0 tags.

**Requirements satisfied:** CLEAN-01, CTRL-01

**5 inline close-gate fixes (no v1013.1 deferrals):**
- `5b965cfd` — WFS-04 layer 2 (abstract→concrete geometry-type normalization)
- `831b691f` — GPKG-03 fan-out 3-bug close (migration renumber + defer race + file-cleanup race)
- `d24371ed` — BSE-01 load-time apply path (G-09/G-10)
- `a400eb89` — E2E fix + duplicate camelCase persistence
- `ec5c2ce5` — Plan QA revisions

**Live MCP re-verify:** 12/12 gates PASS across builder + shared + embed contexts.

## Net Deliverables

- **4 phases / 15 plans / 10 requirements** (all satisfied)
- **5 inline close-gate fixes** (A-02 inline-fix posture honored — zero v1013.1)
- **Smoke gates green:** typecheck 0, vitest 2091/2091, e2e:smoke:builder 25/0/1 (was 10/2/13 pre-fix), i18n 2/2
- **Live MCP re-verify:** 12/12 PASS (5 ROADMAP-named + 7 BSE-01 sub-gates)
- **7 datasets + 1 map deleted** at CLEAN-01 close
- **CHANGELOG `[1.3.0]`** populated
- **Tags `v1013` + `v1.3.0`** cut locally (per A-04 user decision: not pushed)

## Tech-Debt Followups (queued for v1014)

- TECH-DEBT-GPKG-03-ORPHAN-CLEANUP — fan-out staging file sweep
- TECH-DEBT-BSE-01-LIVE-RESET-REVERT — pre-override paint memoization
- TECH-DEBT-VITE-STALE-CACHE — `/smoke-check` served-vs-source verification
- maps/router.py decomposition (1761 LOC vs 1800-LOC carve-out cap)
- search/router.py decomposition (1515 LOC at 1600 cap)

## Audit

See [v1013-MILESTONE-AUDIT.md](../v1013-MILESTONE-AUDIT.md) — status PASSED, 10/10 requirements satisfied.
