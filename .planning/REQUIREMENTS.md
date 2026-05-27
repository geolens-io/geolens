# Requirements: GeoLens v1030 Map Builder Polish Sweep

**Defined:** 2026-05-27
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Milestone goal:** Systematically walk every existing map across layer types and prove builder/viewer/AI/sharing quality via live Playwright MCP, closing surfaced gaps and shipping easy-win UX enhancements.

## v1 Requirements

Requirements for v1030. Each maps to a roadmap phase in the 7-phase structure (1133 → 1134 → {1135 || 1136 || 1137} → 1138 → 1139). The audit-first Phase 1133 (`WALK-*`) is load-bearing — it produces the ground-truth backlog that downstream phases verify against `todo.md` and the v1011/v1028 milestone records.

### WALK — Audit-First Walkthrough

- [x] **WALK-01**: Live Playwright MCP walkthrough of canonical ADK map + representative maps covering every render mode (fill / line / circle / symbol / heatmap / cluster / raster / basemap / DEM/terrain) produces `.planning/phases/1133-*/BUILDER-WALKTHROUGH-AUDIT.md` triaged P0/P1/P2 with one finding per surface
- [x] **WALK-02**: Cross-reference matrix in audit doc lists every `/ai/*` endpoint × frontend consumer hook and confirms each call site has `enabled: !!token && aiEnabled` gating (v1010.2 SF-06 recurrence guard — Pitfall #4)
- [x] **WALK-03**: `todo.md` staleness check — every item in `todo.md` lines 96-171 cross-referenced against v1011 / v1028 / v1029 milestone records; flag items already shipped vs genuine regressions vs new gaps in the audit doc
- [x] **WALK-04**: v1026 reconciler + v1027 typed action-boundary + v1008 unified-stack contract verification on clean `main` post-`3ed5ceb3` — `grep -nE 'map\.setPaintProperty|map\.setLayoutProperty' frontend/src --include="*.ts*" -r` returns only `layer-adapters/` + `map-sync.ts` hits, and `BuilderLayerAction` union remains the only mutation entry point
- [x] **WALK-05**: Thumbnail-capture pipeline produces (or can produce) a 1200×630 variant suitable for `og:image`; if no, SHARE-08 OG-cards officially flagged to v1031 in REQUIREMENTS.md Future Requirements

### MAP — Tier-1 Bugs & Smaller-Screen Polish

- [x] **MAP-17**: User can delete a layer across every render mode (fill / line / circle / symbol / heatmap / cluster / raster) without leaving orphan sources, layer-stack entries, or save/dirty-state drift. Regression pin in `frontend/src/components/builder/__tests__/use-builder-layers.test.tsx`. Source: `todo.md` line 146.
- [x] **MAP-18**: User can toggle layer visibility off/on across every render mode and see the change immediately on the map. Regression pin per adapter in `frontend/src/components/builder/layer-adapters/__tests__/`. Likely the v1011 BUG-01 `syncVisibility` initial-layout pattern recurring across multiple adapters — audit all adapters, not only the named one. Source: `todo.md` line 143.
- [ ] **MAP-16**: User can rename a layer group and the rename text input receives focus reliably (rAF-deferred per v1011 BUG-03 dnd-kit / Radix focus race). Regression pin in `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx`. Source: `todo.md` line 145.
- [ ] **MAP-07**: At ≤ 800 px the right-sidebar Sheet does not overlap the MapLibre zoom/Navigation controls (fix sidebar collapse trigger — do NOT move NavigationControl from `top-left`; Pitfall #10). Source: `todo.md` line 147.
- [ ] **MAP-08**: At ≤ 800 px the lat/long readout pill does not overlap the map widget container. Verify v1011 RESP-02 fix still live; pin a positive-form `queryBy*` regression test in `MapCoordReadout.test.tsx`. Source: `todo.md` line 148.
- [ ] **MAP-09**: At ≤ 800 px the basemap selector renders a single close button (no double-X). Verify v1011 RESP-03 fix still live across `<SheetContent>` callers. Source: `todo.md` line 149.
- [ ] **MAP-10**: Every right-sidebar `<SheetContent>` opts out of duplicate-X via `showCloseButton={false}` per v1011 RESP-03 contract; regression pin in `frontend/src/components/builder/__tests__/sheet-close-button.test.tsx`. Source: generalized from `todo.md` line 149.
- [ ] **MAP-19**: Map container does not scroll the page body during pan/zoom; verify pointer/wheel event handling and `touch-action: none` boundaries on `BuilderMap`. Source: `todo.md` line 136.
- [ ] **MAP-20**: Filter pills do not collide with the measure-widget chrome at any sidebar collapse state. Source: `todo.md` line 103.
- [ ] **MAP-22**: Notes icon shows a presence indicator (dot / count) when notes exist on the active map; reads from existing notes state, no new endpoint. Source: `todo.md` line 101.

### AI — Chat Polish (depends on MAP)

- [ ] **AI-01**: User can confirm-before-apply destructive AI actions (add_layer / remove_layer); CONTEXT.md picks shape A (pre-apply + atomic undo) or shape B (`pendingLayers` staging buffer) before plan-01 — DO NOT MIX (Pitfall #3). Regression test: "rejecting a staged action leaves layers byte-equal to pre-prompt state." Source: `todo.md` line 108.
- [ ] **AI-08**: User can ask data-analysis questions ("which datasets cover X", "summarize this layer's attributes") and see results in an inline card via the existing `show_query_result` action shape; no new BuilderLayerAction variant beyond extending `add_dataset`. Source: `todo.md` line 171.
- [ ] **AI-09**: Action preview chips render before destructive actions apply, showing the staged change in human-readable form ("Add 'NYC subway' below 'Counties'"); tied to AI-01 staging shape.
- [ ] **AI-05**: Suggestion chips become viewport-aware (the chip list reflects the current camera + selected-layer context, not the static default list).
- [ ] **AI-02**: Provider-disabled UAT: with `AI_ENABLED=false` on the local stack, the AI rail panel surfaces an actionable disabled state (no inert dead-end button); regression pin in `ChatPanel.test.tsx`. Re-verify v1028 AI-FU disposition holds.
- [ ] **AI-03**: Provider-error UAT: with an invalid provider key, the AI panel surfaces a recoverable error banner with a "retry" affordance; no silent fail.
- [ ] **AI-04**: `_validate_chat_layers` visibility-filter decision documented explicitly in `chat_actions.py` docstring — either filter hidden layers OR document "analyze sees all layers regardless of visibility" with rationale (Pitfall #5).

### EDITOR — Per-Render-Mode Editor Polish (parallel to AI)

- [ ] **EDITOR-RASTER-01**: User can adjust raster brightness via a slider in `RasterEditor.tsx`; routed through `RasterAdapter` `*_OWNED_PAINT_PROPERTIES` extension; debounced via v1010 `coalesceFrame` (100ms opacity, 200ms color); save/reload symmetry vitest mandatory.
- [ ] **EDITOR-RASTER-02**: User can adjust raster contrast via a slider; same contract as EDITOR-RASTER-01.
- [ ] **EDITOR-RASTER-03**: User can adjust raster saturation via a slider; same contract.
- [ ] **EDITOR-RASTER-04**: User can adjust raster hue-rotate via a slider + a Reset button restores all 4 sliders to default; pinned by save/reload + style-JSON round-trip tests.
- [ ] **EDITOR-LINE-01**: User can pick `line-cap` (butt / round / square) in `LineEditor.tsx`; LineAdapter extends `*_OWNED_LAYOUT_PROPERTIES` (NOT paint).
- [ ] **EDITOR-LINE-02**: User can pick `line-join` (bevel / round / miter) in `LineEditor.tsx`; same LAYOUT-not-PAINT contract.
- [ ] **EDITOR-FILL-04**: When a fill layer uses 3D extrusion via `paint._height_column`, FillEditor surfaces a "Range: X–Y, N features" hint from the dataset sample values; verify `dataset_sample_values` carries enough metadata in WALK-01.
- [ ] **EDITOR-BASEMAP-02**: User can pick a "No basemap" preset that produces a transparent / single-color background; persists round-trip; verified in viewer/embed.
- [ ] **EDITOR-BASEMAP-03**: DETAIL LEVEL toggle remains absent from `BasemapSublayerEditorScene` (v1011 INV-01 disposition); positive-form `queryBy*` regression pin in `frontend/src/components/builder/__tests__/BasemapSublayerEditor.test.tsx`.

### SHARE — Sharing/Embed Polish (parallel to AI/EDITOR)

- [ ] **SHARE-02**: Allowed origins display as removable chips after Save (replacing the comma-separated input as the source of truth); chip input round-trips via PATCH `allowed_origins`.
- [ ] **SHARE-04**: User can pick expiration via presets (1 day / 7 days / 30 days / 1 year / Never) in the SharePanel; custom-date input remains as the secondary affordance.
- [ ] **SHARE-07**: Shared and embed views render "Powered by GeoLens" branding when `useEdition()` returns the community edition; suppressed under enterprise edition. Source: `todo.md` line 151.
- [ ] **SHARE-09**: Shared and embed views render the map title + legend by default; export captures (PNG/PDF if present) include both. Source: `todo.md` line 151.
- [ ] **SHARE-03**: Embed-preview iframe pane in the SharePanel mirrors the live embed view at the configured allowed-origin; iframe sandbox stays `allow-scripts` only (no `allow-same-origin` — SEC-07 / M-70 contract at `SharePanel.tsx:36`). Conditional: proceed only if sandbox feasibility holds in WALK-05; else flag v1031.
- [ ] **SHARE-06**: PATCH `allowed_origins` round-trip vitest covers canonical-form normalization (trailing slash, case, port) — defensive against Pitfall #8.

### EASY — Easy-Win Sweep

- [ ] **EASY-02**: Cmd/Ctrl+S triggers map Save when the builder is focused; no-op when the dialog/modal is open; visible toast.
- [ ] **EASY-11**: PopupConfigEditor and popup renderer support URLs (auto-linkify) and basic media (image preview). Source: `todo.md` lines 96 + 163.
- [ ] **EASY-18**: When a layer renders zero features (filter eliminated all rows, or empty source), the LayerEditorPanel surfaces a "0 features — check your filter" hint with a "clear filter" button.

### QA — Quality Sweep & Close-Gate

- [ ] **QA-01**: Live Playwright MCP smoke against `localhost:8080` at 1440 × 900, 800 × 600, and 414 × 896 viewports — every render mode renders, layer ops work, save persists, shared/embed parity holds, zero browser-console errors.
- [ ] **QA-02**: Live Playwright MCP smoke with `AI_ENABLED=false` — AI rail surfaces actionable disabled state, no inert button, no console error.
- [ ] **QA-03**: `npm run typecheck` exit 0, vitest green, `npm run lint` exit 0, `e2e:smoke:builder` green, i18n parity (de/es/fr) 2/2.
- [ ] **QA-04**: CHANGELOG `[Unreleased]` populated for v1030 with the measured numbers (RasterEditor stub closed, line-cap/join added, AI confirm shape, share polish set); OpenAPI snapshot diff regenerated where backend `maps/router.py` or `ai/router.py` changed; SDK regenerated to match.

## v2 Requirements

Deferred to v1031+. Tracked but not in current roadmap.

### Render-mode expansion

- **EDITOR-FILL-01**: `fill-pattern` (sprite upload + selection flow) — too big for polish milestone.
- **EDITOR-DEM-04**: Contour-line overlay control — feature, not polish.
- **EDITOR-DEM-05**: Hypsometric tint color ramps for terrain — feature, not polish.
- **EDITOR-RASTER-COLORMAP**: Stretch / colormap UI for single-band rasters — depends on backend colormap-render path scoping.

### Share/embed feature expansion

- **SHARE-08**: OG-image / social-card meta on shared links — DEFERRED to v1031 per Phase 1133 WALK-05 disposition. The live thumbnail pipeline produces 400×250 JPEG only (`use-builder-save.ts:33-34`). A 1200×630 variant requires either dual capture (Path A: backend column + route) or backend resize pipeline (Path B), both outside the v1030 polish boundary. See Future Requirements below.

### Editor convenience

- **EDITOR-SYMBOL-04**: Categorical icon mapping with real distinct-value query — depends on `useColumnDistinctValues` hook existence (resolved in WALK-01).
- **EDITOR-BASEMAP-06**: Custom basemap style URL override — architecture-shaped, defer.

### Layer-type expansion (explicit defer)

- **Text/Annotation layer type** ("Render as Text") — `todo.md` line 160. Defer until layer-type expansion milestone.
- **Draw/annotation layer (text, shapes)** — `todo.md` line 100. Defer.
- **LiDAR support** — `todo.md` line 154. Defer.

## Out of Scope

Explicitly excluded from v1030. Documented to prevent scope creep into polish milestone.

| Feature | Reason |
|---------|--------|
| Builder architecture rewrites | v1027 architecture milestone already shipped; polish is verification, not refactor (Pitfall #12) |
| New LLM provider integrations | AI provider work belongs in a dedicated AI milestone; v1028 AI-FU pinned Anthropic + OpenAI-compatible as sufficient |
| New connector backends (S3 / DuckDB / BigQuery / Athena / etc) | `todo.md` line 110 — large feature surface, not polish |
| Marketing / docs site work | Lives in `~/Code/getgeolens.com/.planning/` (moved 2026-04-26) |
| Enterprise edition changes | Lifecycle covered by v13.2; SAML / enterprise overlays out of polish scope |
| Large new feature builds | Annotation/draw layer, LiDAR support, Text-as-layer-type, AI Skills Repo — defer to feature milestones |
| AI inline editor / multi-turn approve / model picker / named conversations | Anti-features per FEATURES.md AI-A1..A4 |
| Per-viewer auth / collaborator presence / public-directory listing / password protection | Anti-features per FEATURES.md SHARE-A1..A4 |
| Vercel AI SDK / QR-code libs / OG-image stacks (`@vercel/og` / satori) / `react-share` / `copy-to-clipboard` / `chromakit` / `culori` | STACK explicit do-NOT-add list |
| Connect functionality (S3, DuckDB, BigQuery, Athena, Redshift, OSM, Overture) | `todo.md` line 110 — out of polish scope |
| "1-2 cool demo maps" feature work | `todo.md` line 112 — out of polish scope |
| Enterprise → community deactivation flow | `todo.md` line 111 — covered by v13.2 lifecycle |
| GH #101 tmpfs follow-up live UAT | `todo.md` line 117 — separate quick-task track |
| GH #100 worker MissingGreenlet debug | `todo.md` line 120 — separate `/gsd-debug` track |
| DEM sizing decision | `todo.md` line 124 — quick-task track |

## Traceability

Phase-to-requirement mapping. Every v1 requirement maps to exactly one phase. Per-REQ-ID rows for unambiguous coverage; flip Status to `Complete` in the same commit as the closing phase SUMMARY (v1019 TD-13 rule).

| Requirement | Phase | Status |
|-------------|-------|--------|
| WALK-01 | Phase 1133 | Complete |
| WALK-02 | Phase 1133 | Complete |
| WALK-03 | Phase 1133 | Complete |
| WALK-04 | Phase 1133 | Complete |
| WALK-05 | Phase 1133 | Complete |
| MAP-07 | Phase 1134 | Pending |
| MAP-08 | Phase 1134 | Pending |
| MAP-09 | Phase 1134 | Pending |
| MAP-10 | Phase 1134 | Pending |
| MAP-16 | Phase 1134 | Pending |
| MAP-17 | Phase 1134 | Complete |
| MAP-18 | Phase 1134 | Complete |
| MAP-19 | Phase 1134 | Pending |
| MAP-20 | Phase 1134 | Pending |
| MAP-22 | Phase 1134 | Pending |
| AI-01 | Phase 1135 | Pending |
| AI-02 | Phase 1135 | Pending |
| AI-03 | Phase 1135 | Pending |
| AI-04 | Phase 1135 | Pending |
| AI-05 | Phase 1135 | Pending |
| AI-08 | Phase 1135 | Pending |
| AI-09 | Phase 1135 | Pending |
| EDITOR-RASTER-01 | Phase 1136 | Pending |
| EDITOR-RASTER-02 | Phase 1136 | Pending |
| EDITOR-RASTER-03 | Phase 1136 | Pending |
| EDITOR-RASTER-04 | Phase 1136 | Pending |
| EDITOR-LINE-01 | Phase 1136 | Pending |
| EDITOR-LINE-02 | Phase 1136 | Pending |
| EDITOR-FILL-04 | Phase 1136 | Pending |
| EDITOR-BASEMAP-02 | Phase 1136 | Pending |
| EDITOR-BASEMAP-03 | Phase 1136 | Pending |
| SHARE-02 | Phase 1137 | Pending |
| SHARE-03 | Phase 1137 | Pending |
| SHARE-04 | Phase 1137 | Pending |
| SHARE-06 | Phase 1137 | Pending |
| SHARE-07 | Phase 1137 | Pending |
| SHARE-09 | Phase 1137 | Pending |
| EASY-02 | Phase 1138 | Pending |
| EASY-11 | Phase 1138 | Pending |
| EASY-18 | Phase 1138 | Pending |
| QA-01 | Phase 1139 | Pending |
| QA-02 | Phase 1139 | Pending |
| QA-03 | Phase 1139 | Pending |
| QA-04 | Phase 1139 | Pending |

**Coverage:**
- v1 requirements: 44 total (5 WALK + 10 MAP + 7 AI + 9 EDITOR + 6 SHARE + 3 EASY + 4 QA)
- Mapped to phases: 44/44 (100% coverage)
- Unmapped: 0
- Duplicates (REQ in >1 phase): 0

**Phase distribution:**

| Phase | Count | REQ IDs |
|-------|-------|---------|
| 1133 | 5 | WALK-01..05 |
| 1134 | 10 | MAP-07/08/09/10/16/17/18/19/20/22 |
| 1135 | 7 | AI-01/02/03/04/05/08/09 |
| 1136 | 9 | EDITOR-RASTER-01..04, EDITOR-LINE-01/02, EDITOR-FILL-04, EDITOR-BASEMAP-02/03 |
| 1137 | 6 | SHARE-02/03/04/06/07/09 |
| 1138 | 3 | EASY-02/11/18 |
| 1139 | 4 | QA-01/02/03/04 |
| **Total** | **44** | — |

---
*Requirements defined: 2026-05-27*
*Traceability committed: 2026-05-27 (roadmapper) — 44/44 mapped, 0 orphans, 0 duplicates*

---

## Future Requirements (v1031+)

Requirements deferred from v1030 with explicit rationale. Each entry documents why it was deferred and what is required to ship it in a future milestone.

### SHARE-08: OG-image / social-card meta on shared links

**Deferred from:** v1030 (Phase 1133 WALK-05 disposition, 2026-05-27)
**Why deferred:** The live thumbnail pipeline produces 400×250 JPEG only (`use-builder-save.ts:33-34`, `thumbW = 400`, `thumbH = 250`). A 1200×630 variant requires either dual capture (Path A: backend `og_image_uri` column + upload route + serve route, ~1 day) or backend resize pipeline (Path B: server-side resize on upload, ~1.5 days). Both expand scope beyond the v1030 polish boundary. No v1030 v1 REQ depends on OG-image meta; the existing 400×250 thumbnail fully satisfies `useMapThumbnail` catalog consumers.
**What's required to ship:** Pick Path A or Path B in a v1031 audit. Path A: add nullable `og_image_uri` column (migration), `PUT /maps/{id}/og-image/` upload route, `GET /maps/{id}/og-image/` serve route; frontend adds a second `doCapture` invocation at 1200×630 alongside the existing 400×250 in `captureThumbnail`. Path B: backend receives the native canvas capture (~1440×900) and resizes to both variants on upload; frontend changes the source image sent (larger, no frontend dual-capture). Either path then wires the `og_image_uri` into the shared-viewer `<meta property="og:image">` tag.
**Out-of-scope libraries:** `@vercel/og`, `satori` (on STACK explicit do-NOT-add list in REQUIREMENTS.md Out of Scope).
**Cross-reference:** `.planning/phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md#share-08-disposition`
