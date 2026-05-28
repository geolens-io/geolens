# Requirements: GeoLens — v1032 Builder Carry-Forward Resolution

**Defined:** 2026-05-28
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

Milestone v1032 decisively closes the v1031 carry-forward tail without inflating into another full builder sweep. Two work areas: (1) resolve the deferred contour control via a spike-first harden-or-cut decision on the `maplibre-contour@0.1.0` worker, and (2) finish the single-band raster stretch strategies (`percentile` / `stddev`) that currently fall back to `minmax`. Spike-first discipline matches v1019-v1022.

## v1 Requirements

### Contour Disposition (spike-first)

The v1031 close-gate gated the contour control off (`CONTOUR_CONTROL_ENABLED=false` at `DEMEditorScene.tsx:28`) because the `maplibre-contour@0.1.0` worker emits ~28 MapLibre error events on enable. `contour-sync.ts` (219 LOC) + its tests + 5 `it.skip` `DEMEditorScene` tests are retained dormant; `syncContourLayer` is still called from `map-sync.ts:919` but no-ops when `_contour-enabled` is absent. STATE.md frames re-enable as "flip one boolean" — this milestone tests that claim against evidence and resolves it either way.

- [x] **CONTOUR-01** (spike): Root-cause the `maplibre-contour` worker instability on enable. Reproduce the ~28 MapLibre error events on the live builder (orchestrator Playwright MCP), inventory them by category, and analyze the worker / isoline-tile / `addProtocol` integration path (note: the `addProtocol` registration bug was already fixed `716b1927`). Produce a spike audit at `.planning/audits/CONTOUR-WORKER-v1032.md` with an evidence-backed **harden-or-cut recommendation** and a rough effort estimate for the harden path.
- [x] **CONTOUR-02** (disposition): Resolve the contour control per CONTOUR-01 evidence — EITHER **harden** (worker enables with zero new console errors; `CONTOUR_CONTROL_ENABLED` flipped to `true`; the 5 dormant `DEMEditorScene` tests un-skipped and passing; live-verified rendering on both builder and viewer) OR **cut cleanly** (remove the `maplibre-contour` dependency, `contour-sync.ts` + its test, the `syncContourLayer` call site at `map-sync.ts:919`, the 5 dormant tests, and the `DEMEditorScene` contour gate + `CONTOUR_CONTROL_ENABLED` flag; add a positive regression pin that the surface stays gone). **Default bias: cut if hardening is not clearly cheap** per the spike estimate.

### Single-Band Raster Stretch Stats

`backend/app/processing/tiles/router.py:437` accepts `stretch: Literal["minmax","percentile","stddev"]`, but `:488` logs a warning and falls back to `minmax` for anything non-minmax. This area finishes the two unimplemented strategies. Planning determines backend-only vs backend+frontend wiring (verify whether the RasterEditor stretch control already sends the param).

- [x] **RASTER-STRETCH-01**: Selecting `percentile` stretch on a single-band raster computes per-band percentile breakpoints (default 2nd/98th, consistent with the existing quicklook path) and drives a correct Titiler `rescale`, instead of falling back to `minmax`.
- [x] **RASTER-STRETCH-02**: Selecting `stddev` stretch on a single-band raster computes per-band mean ± N·σ breakpoints and drives a correct Titiler `rescale`, instead of falling back to `minmax`.

### Quality & Close-Gate

- [x] **QA-01**: Builder verified via orchestrator-driven live Playwright MCP smoke on `localhost:8080` — the contour surface in its final state (hardened control renders cleanly with no console errors, OR the cut surface is absent and the DEM editor is error-free) plus the raster `percentile`/`stddev` stretch render. Evidence doc captured (`.planning/phases/.../MCP-SMOKE.md`).
- [x] **QA-02**: Touched-surface gates green — frontend typecheck + lint + vitest, focused backend pytest, `e2e:smoke:builder`, and i18n parity (en/de/es/fr).
- [x] **QA-03**: CHANGELOG updated for v1032; OpenAPI + Python/TypeScript SDK regenerated IF backend routes/schema changed (verify — the `stretch` param already exists in the tile route schema). Public-version bump decided (1.6.0 → 1.6.1 patch vs 1.7.0 minor).

## Future Requirements (v1033+)

- **RASTER-STRETCH-03**: Multi-band per-band stretch stats (this milestone scopes single-band; RGB/multi-band stretch is a larger surface).
- **RASTER-STRETCH-UI-01**: User-configurable percentile bounds and σ multiplier in the RasterEditor (this milestone uses sensible defaults).
- **RASTER-STRETCH-UI-02**: Decouple stretch from colormap so `percentile`/`stddev` also apply on the default grayscale render (today `buildColormapTileUrl` only forwards `stretch=` alongside a non-gray colormap, so selecting a stretch on the gray colormap is a no-op). Alternatively gate the stretch control on a non-gray colormap. Pre-existing coupling surfaced by v1032 (milestone audit tech-debt item).
- 999.18 editor-convenience + layer-type expansion (EDITOR-SYMBOL-04, EDITOR-BASEMAP-06, LAYER-TEXT-01, LAYER-DRAW-01, LAYER-LIDAR-01) remain parked in the 999.18 backlog register.

## Out of Scope

Explicitly excluded from v1032. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Alternative contour libraries / custom isoline renderer | If contour is cut, it is cut — not re-implemented on a different dependency this milestone. A future feature milestone may revisit contour with a different approach. |
| Nyquist VALIDATION.md formalization (1140-1143) | Intentionally skipped to keep v1032 lean; underlying coverage already strong (vitest 2599/2599, pytest 181/181, e2e 26/26). Optional `/gsd:validate-phase` later if formal artifacts are desired. |
| CI-01 GH Actions billing | Ops task (operator must resolve org billing at the org settings), not a code phase. Standing blocker, unblocked independently. |
| Multi-band raster stretch | Single-band only this milestone (see Future RASTER-STRETCH-03). |
| Broad builder / UI rework | v1032 is a targeted carry-forward close on the existing v1026/v1027 substrate — no controller/action-boundary widening, no renderer additions. |
| New LLM provider integrations | Out of milestone theme; AI chat substrate unchanged. |
| Marketing / docs-site work | Lives in the `getgeolens.com` sibling repo. |
| Open-core / Cloud backlog (999.6 / 999.13-16) | Tenant scoping, connector registry, Helm/AMI, SBOM, schemas package — separate larger initiatives. |

## Traceability

Which phases cover which requirements. Continues phase numbering from 1143 → starts at 1144.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONTOUR-01 | Phase 1144 | Complete (→ CUT) |
| CONTOUR-02 | Phase 1145 | Complete (CUT) |
| RASTER-STRETCH-01 | Phase 1146 | Complete |
| RASTER-STRETCH-02 | Phase 1146 | Complete |
| QA-01 | Phase 1147 | Complete |
| QA-02 | Phase 1147 | Complete |
| QA-03 | Phase 1147 | Complete |

**Coverage:**
- v1 requirements: 7 total
- Mapped to phases: 7 (100%)
- Unmapped: 0
- Delivered: 7/7 ✓ (CONTOUR-01 spike; CONTOUR-02 cut; RASTER-STRETCH-01/02; QA-01/02/03)

---
*Requirements defined: 2026-05-28 — milestone v1032 Builder Carry-Forward Resolution.*
