# Roadmap: GeoLens

## Current Milestone

**v1030 Map Builder Polish Sweep** — Phases 1133-1139 (active; 7 phases, 44 v1 requirements across WALK/MAP/AI/EDITOR/SHARE/EASY/QA categories).

**Milestone goal:** Systematically walk every existing map across layer types and prove builder/viewer/AI/sharing quality via live Playwright MCP, closing surfaced gaps and shipping easy-win UX enhancements.

**Substrate baseline:** v1008 unified stack, v1026 style reconciler, v1027 typed action boundary, v1028 AI polish, v1029 DCAT 3.0, in-flight share/access/chat polish at `3ed5ceb3` (now on `main`).

**Hard non-goals (DO NOT pull in):** annotation/draw layer, LiDAR support, "Render as Text" layer type, new LLM provider integrations, new connector backends, builder architecture rewrites, marketing/docs site work, enterprise edition changes, large new feature builds. STACK explicit do-NOT-add list: Vercel AI SDK, `qrcode.react`, `@vercel/og`/satori, `react-share`, `copy-to-clipboard`, `chromakit`/`culori`.

## Phases

- [x] **Phase 1133: Audit-First Builder Walkthrough** — Live Playwright MCP walkthrough across every render mode; produces `BUILDER-WALKTHROUGH-AUDIT.md` (P0/P1/P2 triage) + AI consumer-gating matrix + `todo.md` staleness cross-reference. (completed 2026-05-27)
- [x] **Phase 1134: Map Functionality and Smaller-Screen Polish** — Tier-1 bugs (delete-layer, visibility-toggle, rename-group focus) + ≤800px layout collisions; stabilizes `dispatchLayerAction` boundary before Phase 1135. (completed 2026-05-27)
- [x] **Phase 1135: AI Chat Confirm-Before-Apply and Analysis Polish** — Confirm-before-apply staging (shape A or B picked in CONTEXT.md before plan-01), action preview chips, viewport-aware suggestions, data-analysis inline card, disabled/error empty-state re-verify. (completed 2026-05-27)
- [ ] **Phase 1136: Per-Render-Mode Editor Polish** — RasterEditor brightness/contrast/saturation/hue + reset; LineEditor line-cap/line-join; FillEditor extrusion range hint; BasemapEditor "No basemap" preset + DETAIL LEVEL stays gone.
- [ ] **Phase 1137: Sharing and Embed Polish** — Allowed-origins as chips; expiration presets; "Powered by GeoLens" branding (community edition) + legend+title in export; conditional iframe preview.
- [ ] **Phase 1138: Easy-Win Sweep** — Cmd/Ctrl+S, popup URL/media handling, empty-layer state.
- [ ] **Phase 1139: Quality Sweep and Playwright Close-Gate** — Live MCP at 1440×900 / 800×600 / 414×896, disabled-AI smoke, typecheck/lint/vitest/e2e/i18n parity, CHANGELOG + OpenAPI/SDK refresh where backend changed.

## Phase Details

### Phase 1133: Audit-First Builder Walkthrough
**Goal**: Produce a single ground-truth backlog (`BUILDER-WALKTHROUGH-AUDIT.md`) that downstream phases verify against, plus the AI consumer-gating matrix and a `todo.md` staleness pass that prevents already-shipped items from being re-scheduled.
**Depends on**: Nothing (first phase). Runs against clean `main` post-`3ed5ceb3`.
**Requirements**: WALK-01, WALK-02, WALK-03, WALK-04, WALK-05
**Success Criteria** (what must be TRUE):
  1. `BUILDER-WALKTHROUGH-AUDIT.md` exists at `.planning/phases/1133-*/` with one finding per surface, triaged P0/P1/P2, covering every render mode (fill / line / circle / symbol / heatmap / cluster / raster / basemap / DEM/terrain) and citing the canonical ADK map plus at least one representative map per mode.
  2. The audit doc contains a complete AI consumer-gating matrix: every `/ai/*` endpoint × frontend hook with explicit columns for `enabled: !!token && aiEnabled` gating, 403 distinct surface, and 503 distinct surface (Pitfall #4).
  3. Each `todo.md` line 96-171 item is classified as `closed-in-prior-milestone` / `live-regression` / `genuine-new-gap` with a milestone citation per closed item (Pitfall #13).
  4. v1027 typed action-boundary + v1026 reconciler + v1008 unified-stack invariants verified live: `grep` for `map.setPaintProperty` / `map.setLayoutProperty` outside `layer-adapters/` and `map-sync.ts` returns clean; `BuilderLayerAction` union remains the only mutation entry point.
  5. SHARE-08 (OG-cards) disposition recorded: 1200×630 thumbnail variant exists OR a Future Requirements entry flags SHARE-08 to v1031 with rationale.
**Plans**: 5 plans
- [x] 1133-01-PLAN.md — Live Playwright MCP walkthrough + audit-doc skeleton + Phase 1134-1138 routing table (WALK-01)
- [x] 1133-02-PLAN.md — AI Consumer-Gating Matrix (Pitfall #4 / v1010.2 SF-06 sibling-hook sweep) (WALK-02)
- [x] 1133-03-PLAN.md — todo.md L96-171 staleness pass with milestone citations (WALK-03)
- [x] 1133-04-PLAN.md — Invariant grep checks: v1008/v1026/v1027 contracts on clean main (WALK-04)
- [x] 1133-05-PLAN.md — SHARE-08 thumbnail-variant + SHARE-03 iframe-sandbox disposition + audit sign-off (WALK-05)
**UI hint**: yes

### Phase 1134: Map Functionality and Smaller-Screen Polish
**Goal**: Close the Tier-1 `todo.md` bug-shape items (delete-layer, visibility-toggle, rename-group focus) and the ≤800px layout collisions so the `dispatchLayerAction` boundary is stable before Phase 1135's AI staging work touches it.
**Depends on**: Phase 1133 (audit names exact failure modes per `todo.md` cross-reference; smaller-screen audit reads v1011 RESP-01/02/03 first per Pitfall #10).
**Requirements**: MAP-07, MAP-08, MAP-09, MAP-10, MAP-16, MAP-17, MAP-18, MAP-19, MAP-20, MAP-22
**Success Criteria** (what must be TRUE):
  1. User can delete a layer across every render mode (fill / line / circle / symbol / heatmap / cluster / raster) without leaving orphan sources, layer-stack entries, or save/dirty-state drift; regression pinned in `use-builder-layers.test.tsx`.
  2. User can toggle layer visibility off/on for every render mode and see the canvas reflect the change immediately; per-adapter regression pin in `layer-adapters/__tests__/` covers the v1011 BUG-01 `syncVisibility` initial-layout pattern across ALL adapters, not just the named one.
  3. User can rename a layer group and the text input receives focus on first paint via rAF-deferred focus (v1011 BUG-03 pattern); regression pin in `UnifiedStackPanel.test.tsx`.
  4. At ≤800px viewport: right-sidebar Sheet does not overlap the NavigationControl (sidebar collapse trigger fixed; NavigationControl stays at `top-left` per Pitfall #10), lat/long readout does not overlap the widget container, and every `<SheetContent>` in the builder canvas opts out of duplicate-X via `showCloseButton={false}` (negative-control pin in `sheet-close-button.test.tsx` per Pitfall #11).
  5. Map container does not scroll the page body during pan/zoom; filter pills do not collide with the measure-widget chrome at any sidebar state; Notes icon shows a presence indicator (dot/count) when notes exist on the active map.
**Plans**: 6 plans
- [x] 1134-01-PLAN.md — Per-adapter regression sweep + raster early-return fix + symbol setFilter migration (MAP-18)
- [x] 1134-02-PLAN.md — Delete-layer adapter-driven companion sweep (MAP-17)
- [x] 1134-03-PLAN.md — Rename-group rAF-deferred focus regression pin (MAP-16)
- [x] 1134-04-PLAN.md — ≤800px sidebar offset + SheetContent grep guard + coord readout pin + filter chip overflow (MAP-07/08/09/10/20)
- [x] 1134-05-PLAN.md — Notes presence dot + MAP-19 scroll-containment regression pin (MAP-19, MAP-22)
- [x] 1134-06-PLAN.md — Live Playwright MCP smoke at 1440×900 / 800×600 / 414×896 (all 10 MAP REQs)
**UI hint**: yes

### Phase 1135: AI Chat Confirm-Before-Apply and Analysis Polish
**Goal**: Add confirm-before-apply staging for destructive AI actions, action preview chips, viewport-aware suggestions, and an inline data-analysis card — all on top of the v1027 typed action boundary without bypassing it.
**Depends on**: Phase 1134 (the `dispatchLayerAction` boundary must be stable; visibility/delete fixes may shift adapter behavior the AI staging tests pin against).
**Requirements**: AI-01, AI-02, AI-03, AI-04, AI-05, AI-08, AI-09

**Pre-plan-01 decision (Pitfall #3, NON-NEGOTIABLE):** CONTEXT.md MUST pick AI confirm-before-apply staging shape A (pre-apply + atomic undo, requires `BuilderActionSource` widening to include `'ai-pending' | 'ai-committed'` and reconciler side-effect gating) OR shape B (`pendingLayers` staging buffer in a new `chat-action-staging.ts` module that sits ABOVE `dispatchLayerAction`). DO NOT MIX shapes — mixing produces partially-applied state on reject and breaks the snapshot/undo contract. Pick before plan-01 commits.

**Success Criteria** (what must be TRUE):
  1. User can preview destructive AI actions (`add_layer`, `remove_layer`) before they apply, accept or reject each staged action, and rejecting leaves the map byte-equal to the pre-prompt layer state; regression test pinned in `ChatPanel.test.tsx`.
  2. Action preview chips render before destructive actions apply, showing the staged change in human-readable form (e.g., "Add 'NYC subway' below 'Counties'"); chips are gated on the same staging shape chosen in CONTEXT.md.
  3. Suggestion chips reflect current viewport + selected-layer context (not the static default list); User can ask data-analysis questions ("which datasets cover X", "summarize this layer's attributes") that render in an inline card via the existing `show_query_result` action (no new BuilderLayerAction variant beyond extending `add_dataset`).
  4. With `AI_ENABLED=false` on the local stack: the AI rail panel surfaces an actionable disabled state (no inert dead-end button), zero console errors, regression pinned in `ChatPanel.test.tsx`. With an invalid provider key: the AI panel surfaces a recoverable error banner with a retry affordance (no silent fail). Every new AI consumer hook is gated on `enabled: !!token && aiEnabled` per the Phase 1133 matrix (v1010.2 SF-06 recurrence guard).
  5. `_validate_chat_layers` visibility-filter decision is documented explicitly in `chat_actions.py` docstring — either it filters hidden layers OR documents "analyze sees all layers regardless of visibility" with rationale (Pitfall #5). Schema-context cache key remains `(map_id, dataset_id)` — no `dataset_id`-only shortcut.
**Plans**: 6 plans
- [x] 1135-01-PLAN.md — chat-action-staging.ts module (Shape B) + useAIAvailability reason field (AI-01, AI-02)
- [x] 1135-02-PLAN.md — ChatPanel staging tray + inline data-analysis card + chip text format (AI-01, AI-08, AI-09)
- [x] 1135-03-PLAN.md — BuilderRail structured disabled-state + ChatPanel recoverable error banner (AI-02, AI-03)
- [x] 1135-04-PLAN.md — Viewport-aware suggestion chips + MapBuilderPage viewport wiring (AI-05)
- [x] 1135-05-PLAN.md — Backend _validate_chat_layers docstring + schema-cache-key regression pin (AI-04)
- [x] 1135-06-PLAN.md — Live Playwright MCP smoke (AI_ENABLED=true 5 surfaces + AI_ENABLED=false rail check)
**UI hint**: yes

### Phase 1136: Per-Render-Mode Editor Polish
**Goal**: Close the per-editor table-stakes gaps (RasterEditor stub → 4 sliders + reset; LineEditor line-cap/line-join; FillEditor extrusion range hint; BasemapEditor "No basemap" preset + DETAIL LEVEL stays gone) by extending v1026 owned-property contracts without introducing direct `map.setPaintProperty` callsites or new contracts. Parallel to Phase 1135.
**Depends on**: Phase 1134 (adapter `syncVisibility` fixes from MAP-18 may touch shared `*-adapter.ts` files; editors layer on top).
**Requirements**: EDITOR-RASTER-01, EDITOR-RASTER-02, EDITOR-RASTER-03, EDITOR-RASTER-04, EDITOR-LINE-01, EDITOR-LINE-02, EDITOR-FILL-04, EDITOR-BASEMAP-02, EDITOR-BASEMAP-03
**Success Criteria** (what must be TRUE):
  1. User can adjust raster brightness, contrast, saturation, and hue-rotate via sliders in `RasterEditor.tsx`; all four route through `RasterAdapter` `*_OWNED_PAINT_PROPERTIES` extension and v1010 `coalesceFrame` (100ms opacity / 200ms color+filter debounces — no direct `map.setPaintProperty` per Pitfall #9). A Reset button restores all four sliders to defaults.
  2. User can pick `line-cap` (butt / round / square) and `line-join` (bevel / round / miter) in `LineEditor.tsx`; LineAdapter extends `*_OWNED_LAYOUT_PROPERTIES` (NOT paint — these are MapLibre layout properties).
  3. When a fill layer uses 3D extrusion via `paint._height_column`, FillEditor displays a "Range: X–Y, N features" hint sourced from `dataset_sample_values` (metadata existence verified during Phase 1133 audit).
  4. User can pick a "No basemap" preset that produces a transparent / single-color background; persists round-trip and renders correctly in viewer/embed. DETAIL LEVEL toggle remains absent from `BasemapSublayerEditorScene` (v1011 INV-01 disposition); positive-form `queryBy*` regression pin asserts the surface stays gone.
  5. Save → reload symmetry vitest covers every new control per render mode (Pitfall #2); style-JSON round-trip test verifies no paint properties leak or are dropped; grep guard verifies no `map.setPaintProperty` / `map.setLayoutProperty` outside `layer-adapters/` + `map-sync.ts` (Pitfall #9).
**Plans**: TBD
**UI hint**: yes

### Phase 1137: Sharing and Embed Polish
**Goal**: Extend `3ed5ceb3`'s `rawShareToken` / `persistedShareTokenHint` separation with chip-based allowed-origins, expiration presets, "Powered by GeoLens" community-edition branding, legend+title in export, and a sandboxed iframe preview (conditional on Phase 1133 sandbox feasibility audit). Parallel to Phases 1135 and 1136.
**Depends on**: Phase 1133 (thumbnail-capture pipeline feasibility for SHARE-08 already routed; iframe sandbox feasibility for SHARE-03 confirmed here).
**Requirements**: SHARE-02, SHARE-03, SHARE-04, SHARE-06, SHARE-07, SHARE-09
**Success Criteria** (what must be TRUE):
  1. Allowed origins display as removable chips after Save (chips replace the comma-separated input as the source of truth post-Save); chip input round-trips via PATCH `allowed_origins` with canonical-form normalization (trailing slash, case, port) covered by vitest (Pitfall #8); CSP `frame-ancestors` directive never contains `*` regardless of input (backend pin).
  2. User can pick expiration via presets (1 day / 7 days / 30 days / 1 year / Never) in the SharePanel; custom-date input remains as the secondary affordance; existing `rawShareToken` survival contract across dialog open/close cycles is preserved by docstring + regression pin (Pitfall #6).
  3. Shared and embed views render "Powered by GeoLens" branding when `useEdition()` returns the community edition and suppress it under enterprise; map title + legend render by default in shared/embed/export PNG; `useEdition()` is read on viewer + ViewerMap + thumbnail-capture paths.
  4. Embed-preview iframe pane in the SharePanel mirrors the live embed view at the configured allowed-origin with sandbox staying `allow-scripts` only (no `allow-same-origin` — SEC-07 / M-70 contract at `SharePanel.tsx:36`). If sandbox feasibility fails the Phase 1133 audit, SHARE-03 is flagged to v1031 and this criterion is documented as deferred-with-rationale.
  5. Embed-token in-flight race is closed via an `inflightEmbedCreate` ref mirroring `ChatPanel`'s `inflightRef` pattern; race regression pinned in `SharePanel.test.tsx` (Pitfall #7).
**Plans**: TBD
**UI hint**: yes

### Phase 1138: Easy-Win Sweep
**Goal**: Close the cross-cutting easy-win items that don't fit any single bucket (keyboard shortcut, popup affordances, empty-layer state). Catches the long tail without forcing items into a previous phase.
**Depends on**: Phases 1134, 1135, 1136, 1137 (so the keyboard listener doesn't conflict with newly-shipped AI or share surfaces, and popup-renderer changes don't regress live polish).
**Requirements**: EASY-02, EASY-11, EASY-18
**Success Criteria** (what must be TRUE):
  1. Cmd/Ctrl+S triggers map Save when the builder is focused and shows a visible toast on success; the listener is gated by the map-builder route, is a no-op when a dialog/modal is open, and does not conflict with browser default save UI.
  2. PopupConfigEditor and the popup renderer detect URLs (auto-linkify) and basic media (`.jpg` / `.png` / `.mp4` plus YouTube URLs render as image / video / link); `{column}` token substitution syntax is documented in the editor.
  3. When a layer renders zero features (filter eliminated all rows or empty source), the LayerEditorPanel surfaces a "0 features — check your filter" hint with a "clear filter" button that dispatches through `BuilderLayerAction` (no map mutation bypass).
  4. Live Playwright MCP at 800px viewport verifies all three easy-wins do not regress any Phase 1134/1136 layout fix (Pitfall #14 — no "small CSS-only change" exception to MCP re-verify).
**Plans**: TBD
**UI hint**: yes

### Phase 1139: Quality Sweep and Playwright Close-Gate
**Goal**: Close v1030 via live Playwright MCP across three viewports, disabled-AI smoke, full test/lint/i18n green, CHANGELOG `[Unreleased]` populated, and OpenAPI/SDK refresh where backend changed. v1027 / v1028 / v1029 hard precedent: close-gate is canonical, not optional.
**Depends on**: Phases 1133-1138 (all milestone work must be in place before final smoke runs).
**Requirements**: QA-01, QA-02, QA-03, QA-04
**Success Criteria** (what must be TRUE):
  1. Live Playwright MCP smoke against `localhost:8080` at 1440×900, 800×600, and 414×896 viewports: every render mode renders, layer ops (add / delete / toggle / rename / drag) work, save persists across reload, shared/embed parity holds, zero browser-console errors per viewport.
  2. Live Playwright MCP smoke with `AI_ENABLED=false`: AI rail surfaces actionable disabled state, no inert button, no `/ai/*` console errors, no broken-canvas state.
  3. `npm run typecheck` exit 0; vitest green (full suite); `npm run lint` exit 0; `e2e:smoke:builder` green; i18n parity (de / es / fr / en) 2/2 (`i18n` script pair).
  4. CHANGELOG `[Unreleased]` populated for v1030 with measured numbers (RasterEditor stub closed → N controls; line-cap/line-join added; AI confirm shape A or B documented; share polish set: chips + presets + branding + legend); OpenAPI snapshot diff regenerated where backend `maps/router.py` or `ai/router.py` changed; SDK regenerated to match (Pitfall #15 — OpenAPI/types diff non-empty AND CHANGELOG silent is a blocker).
**Plans**: TBD
**UI hint**: yes

## Parallelism Notes

After Phase 1134 ships, Phases 1135 / 1136 / 1137 are **independent and can run in parallel** (chat ≠ editors ≠ share) if multiple executors are available. The roadmap lists them sequentially in the phase table for numbering continuity; parallel execution is permitted operationally. Phase 1138 catches the long tail after all three independent phases close. Phase 1139 is the canonical close-gate.

## Coverage Validation

- v1 requirements: 44 total (5 WALK + 10 MAP + 7 AI + 9 EDITOR + 6 SHARE + 3 EASY + 4 QA)
- Mapped to phases: 44/44 (100% coverage, 0 orphans, 0 duplicates)
- Out-of-scope items per REQUIREMENTS.md held as carry-forward register; do not pull into v1030 phases.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1133. Audit-First Builder Walkthrough | v1030 | 5/5 | Complete   | 2026-05-27 |
| 1134. Map Functionality and Smaller-Screen Polish | v1030 | 6/6 | Complete   | 2026-05-27 |
| 1135. AI Chat Confirm-Before-Apply and Analysis Polish | v1030 | 6/6 | Complete   | 2026-05-27 |
| 1136. Per-Render-Mode Editor Polish | v1030 | 0/0 | Not started | - |
| 1137. Sharing and Embed Polish | v1030 | 0/0 | Not started | - |
| 1138. Easy-Win Sweep | v1030 | 0/0 | Not started | - |
| 1139. Quality Sweep and Playwright Close-Gate | v1030 | 0/0 | Not started | - |

## Historical Milestones

- ✅ **v1029 DCAT 3.0** — Phases 1129-1132 (shipped 2026-05-27; DCAT-US Schema v3.0 export/validation routes, official schema foundation, docs, OpenAPI/SDK refresh, and Playwright MCP API close gate) — see [archive](milestones/v1029-ROADMAP.md)
- ✅ **v1028 Map Builder Product Polish** — Phases 1124-1128 (shipped 2026-05-25; Builder Notes clear/persistence fixes, AI unavailable-state polish, workflow regression gates, ADK showcase/shared/embed verification, active smoke path renamed from demo to showcase, no separate demo-instance release gate)
- ✅ **v1027 Map Builder Architecture Simplification** — Phases 1118-1123 (shipped 2026-05-25; builder architecture baseline, basemap controller, shared composition sync, editor scene extraction, typed layer actions, fixture DRY-up, and Playwright MCP target-map verification)
- ✅ **v1026 Mapbuilder Style Reconciler** — Phases 1112-1117 (shipped 2026-05-25; canonical style reconciliation across adapters, manual controls, AI chat actions, persistence/viewer parity, high-DPI sprite routing, terrain activation retry, and Playwright MCP close gate)
- ✅ **v1025 Mapbuilder Polishing** — Phases 1107-1111 (shipped 2026-05-25; ADK 3D Relief deep QA, layer metadata fixes, marketing cartography, Playwright close gate, lint closeout)
- ✅ **v1024 ADK High Peaks Marketing-Ready** — Phases 1101-1106 (completed locally 2026-05-24; ADK marketing data/maps, builder ordering, terrain controls, error hygiene, and Playwright close gate)
- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-02-13)
- ✅ **v1.1 Machine Readability** — Phases 9-13 (shipped 2026-02-14)
- ✅ **v1.2 QA & Polish** — Phases 14-16 (shipped 2026-02-14)
- ✅ **v1.3 Admin Control & Data Lifecycle** — Phases 17-21 (shipped 2026-02-15)
- ✅ **v1.4 Production Readiness** — Phases 22-27 (shipped 2026-02-15)
- ✅ **v1.5 Data Organization & Freshness** — Phases 28-31 (shipped 2026-02-15)
- ✅ **v1.6 UI/UX Polish** — Phases 32-35 (shipped 2026-02-15)
- ⏸️ **v1.7 Marketplace & Distribution** — Phases 36-42 (paused at Phase 40)
- ✅ **v1.8 Map Builder Core** — (shipped 2026-02-17)
- ✅ **v1.9 Map Builder AI** — (shipped 2026-02-21)
- ✅ **v2.0 Natural Earth Seed Script** — Phases 53-55 (shipped 2026-02-22)
- ✅ **v2.1 Service URL Importing** — Phases 56-60 (shipped 2026-02-23)
- ✅ **v2.2 Architecture Simplification** — Phases 61-63 (shipped 2026-02-23)
- ✅ **v2.3 Layer Creation & Editing** — Phases 64-67 (shipped 2026-02-24)
- ✅ **v2.4 Visual Identity & Admin Experience** — Phases 68-71 (shipped 2026-02-24)
- ✅ **v2.5 i18n** — (shipped 2026-02-25)
- ✅ **v2.6 Tile Architecture** — (shipped 2026-02-26)
- ✅ **v3.0 Design Overhaul** — (shipped 2026-02-28)
- ✅ **v5.0 Cloud-Ready Architecture** — (shipped 2026-03-02)
- ✅ **v6.0 Hardening & Production Readiness** — Phases 102-110 (shipped 2026-03-03)
- ✅ **v6.1 Dataset Detail UX & Provenance** — Phases 111-115 (shipped 2026-03-06)
- ✅ **v6.2 Enterprise Configuration & OAuth** — Phases 116-120 (shipped 2026-03-07)
- ✅ **v7.0 Stack Consolidation** — Phases 121-132 (shipped 2026-03-08)
- ✅ **v7.2 Semantic Search (pgvector)** — Phases 133-138 (shipped 2026-03-09)
- ✅ **v7.3 Map Page Polish** — Phases 139-143 (shipped 2026-03-09)
- ✅ **v8.0 Spatial Intelligence** — Phases 144-147 (shipped 2026-03-09)
- ✅ **v8.1 Secure Sharing & Embed Tokens** — Phases 148-151 (shipped 2026-03-10)
- ✅ **v8.2 Share Link Settings** — Phases 152-153 (shipped 2026-03-10)
- ✅ **v9.0 Cloud Marketplace Distribution** — Phases 154-160 (shipped 2026-03-11)
- ✅ **v9.1 Map Experience & Discovery** — Phases 161-164 (shipped 2026-03-11)
- ✅ **v10.0 Raster Support** — Phases 165-170 (shipped 2026-03-14)
- ✅ **v10.1 VRT Raster Mosaics** — Phases 171-177 (shipped 2026-03-15)
- ✅ **v11.0 Performance at Scale** — Phases 178-182 (shipped 2026-03-16)
- ✅ **v12.0 Record-First Discovery Architecture** — Phases 183-190 (shipped 2026-03-17)
- ✅ **v12.1 UI/UX Polish** — Phases 191-194 (shipped 2026-03-18)
- ✅ **v12.2 Record Detail Stabilization** — Phases 195-199 (shipped 2026-03-19)
- ✅ **v12.3 Map Builder Excellence** — Phases 200-205 (shipped 2026-03-21)
- ✅ **v13.0 Open-Core Pre-Release** — Phases 206-211 (shipped 2026-03-27)
- 🚀 **1.0.0 Public Release** — Version reset; backend/frontend bumped to 1.0.0 (shipped 2026-04-01)
- ✅ **v13.1 Open-Core Separation P1** — Phases 212-219 (shipped 2026-04-29) — see [archive](milestones/v13.1-ROADMAP.md)
- ✅ **v13.2 Edition Lifecycle Hardening** — Phases 220-221 (shipped 2026-04-30) — see [archive](milestones/v13.2-ROADMAP.md)
- ✅ **v13.3 Boundary A+ Cleanup** — Phases 222-224 (shipped 2026-05-01) — see [archive](milestones/v13.3-ROADMAP.md)
- ✅ **v13.4 Boundary Closeout** — Phases 225-231 (shipped 2026-05-03) — see [archive](milestones/v13.4-ROADMAP.md)
- ✅ **v13.5 Enterprise Governance Seams** — Phases 232-235 (shipped 2026-05-03) — see [archive](milestones/v13.5-ROADMAP.md)
- ✅ **v13.6 Catalog Maps/Search Service Decomposition** — Phases 236-240 (shipped 2026-05-04) — see [archive](milestones/v13.6-ROADMAP.md)
- ✅ **v13.7 Manifest-Driven Catalog Automation** — Phases 241-245 (shipped 2026-05-04) — see [archive](milestones/v13.7-ROADMAP.md)
- ✅ **v13.8 Map Builder Advanced Styling** — Phases 246-251 (shipped 2026-05-06) — see [archive](milestones/v13.8-ROADMAP.md)
- ✅ **v13.9 Map Builder Closeout** — Phases 252-256 (shipped 2026-05-06) — see [archive](milestones/v13.9-ROADMAP.md)
- ✅ **v13.10 GH Issues Hygiene** — Phase 257 (shipped 2026-05-07) — see [archive](milestones/v13.10-ROADMAP.md)
- ✅ **v13.11 Map Builder Polish & Quality Sweep** — Phases 258-262 (shipped 2026-05-07) — see [archive](milestones/v13.11-ROADMAP.md)
- ✅ **v13.12 Pre-Public Security & Audit Hardening** — Phases 263-270 (shipped 2026-05-07) — see [archive](milestones/v13.12-ROADMAP.md)
- ✅ **v13.13 Backlog Sweep** — Phases 271-279 (shipped 2026-05-07) — see [archive](milestones/v13.13-MILESTONE-AUDIT.md)
- ✅ **v13.14 Smoke Stabilization** — Phases 280-282 (shipped 2026-05-08) — see [archive](milestones/v13.14-ROADMAP.md)
- ✅ **v1000 Map Stack and Basemap Layer Controls** — Phases 1000-1001 (shipped 2026-05-11) — see [archive](milestones/v1000-ROADMAP.md)
- ✅ **v1001 Map Builder UI/UX Polish Sweep** — Phases 1002-1007 (shipped 2026-05-11) — see [archive](milestones/v1001-ROADMAP.md)
- ✅ **v1002 Layer Sidebar + Add Dataset Redesign** — Phases 1008-1013 (shipped 2026-05-12) — see [archive](milestones/v1002-ROADMAP.md)
- ✅ **v1003 Builder v1 Hardening** — Phases 1014-1018 (shipped 2026-05-12) — see [archive](milestones/v1003-ROADMAP.md)
- ✅ **v1004 Builder Renderer Expansion** — Phases 1019-1022 (shipped 2026-05-12) — see [archive](milestones/v1004-ROADMAP.md)
- ✅ **v1005 Builder Point Cluster Foundation** — Phases 1023-1026 (shipped 2026-05-12) — see [archive](milestones/v1005-ROADMAP.md)
- ✅ **v1006 Large Dataset Cluster Scaling** — Phases 1027-1031 (shipped 2026-05-12) — see [archive](milestones/v1006-ROADMAP.md)
- ✅ **v1007 Release Hygiene** — Phase 1032 (shipped 2026-05-12) — see [archive](milestones/v1007-ROADMAP.md)
- ✅ **v1008 Map Builder Sidebar Redesign** — Phases 1033-1038 (shipped 2026-05-14) — see [archive](milestones/v1008-ROADMAP.md)
- ✅ **v1009 Map Builder v1.5 (Polish)** — Phases 1039-1044 (shipped 2026-05-15) — see [archive](milestones/v1009-ROADMAP.md)
- ✅ **v1009.1 Builder Smoke Polish** — Phase 1045 (shipped 2026-05-15) — see [archive](milestones/v1009.1-ROADMAP.md)
- ✅ **v1010 Builder Performance & Code Quality** — Phases 1046-1048 (shipped 2026-05-16) — see [archive](milestones/v1010-ROADMAP.md)
- ✅ **v1010.1 Live Playwright MCP Smoke** — Phase 1049 (shipped 2026-05-17) — see [archive](milestones/v1010.1-ROADMAP.md)
- ✅ **v1010.2 Builder Smoke Carryover** — Phase 1050 (shipped 2026-05-17) — see [archive](milestones/v1010.2-ROADMAP.md)
- ✅ **v1011 Map Builder Polish & Bug Sweep** — Phase 1051 (shipped 2026-05-18) — see [archive](milestones/v1011-ROADMAP.md)
- ✅ **v1011.1 Builder Hygiene Carryover** — Phase 1052 (shipped 2026-05-18) — see [archive](milestones/v1011.1-ROADMAP.md)
- ✅ **v1012 New-User Hardening + Reupload** — Phases 1053-1056 (shipped 2026-05-19, public tag `v1.2.1`)
- ✅ **v1013 Ingest Hardening** — Phases 1057-1060 (shipped 2026-05-20, local tag `v1013`, public tag `v1.3.0`) — see [archive](milestones/v1013-ROADMAP.md)
- ✅ **v1014 Security Audit Remediation** — Phases 1061-1064 (shipped 2026-05-20, local tag `v1014`, public tag `v1.4.0`) — see [archive](milestones/v1014-ROADMAP.md)
- ✅ **v1015 Ingest/Export Lifecycle Hardening** — Phases 1065-1070 (shipped 2026-05-20, local tag `v1015`, public tag `v1.5.0`) — see [archive](milestones/v1015-ROADMAP.md)
- ✅ **v1016 Hardening Sweep** — Phases 1071-1074 (shipped 2026-05-21, local tag v1016, public tag v1.5.1) — see [archive](milestones/v1016-ROADMAP.md)
- ✅ **v1017 Test Infra & Audit Tail** — Phases 1075-1079 (shipped 2026-05-21, local tag `v1017`, public tag `v1.5.2`)
- ✅ **v1018 Hygiene — v1017 Tech-Debt Tail** — Phases 1080-1083 (shipped 2026-05-21, local tag `v1018`, public tag `v1.5.3`) — see [archive](milestones/v1018-ROADMAP.md)
- ✅ **v1019 Hygiene Tail — v1018 Frontend + xdist + Process** — Phases 1084-1086 (shipped 2026-05-22, local tag `v1019`, public tag `v1.5.4`) — see [archive](milestones/v1019-ROADMAP.md)
- ✅ **v1020 Fixture Isolation** — Phases 1087-1090 (shipped 2026-05-22, local tag `v1020`, public tag `v1.5.5`) — see [archive](milestones/v1020-ROADMAP.md)
- ✅ **v1021 Docker Rebuild Sweep + Engine-level Retry** — Phases 1091-1093 (shipped 2026-05-23, local tag `v1021`, public tag `v1.5.6`) — see [archive](milestones/v1021-ROADMAP.md)
- ✅ **v1022 Parallel-Test Cascade Closure + Hygiene Tail** — Phases 1094-1097 (shipped 2026-05-24, local tag `v1022`, public tag `v1.5.7`) — see [archive](milestones/v1022-ROADMAP.md)
- ✅ **v1023 CI Live-Verify + OOS Hygiene Tail** — Phases 1098-1100 (shipped 2026-05-24, local tag `v1023`, public tag `v1.5.8`)

## Backlog

### Phase 999.6: Tenant scoping infrastructure for multi-tenant isolation (BACKLOG — Cloud prerequisite)

**Goal:** [Captured for future planning]
**Requirements:** TBD
**Plans:** 1/1 plans complete
**Source:** `docs-internal/audits/oc-separation-audit-20260426-b.md` §2 (Seam #8) / §7 P3
**Estimated effort:** 1–2 weeks+ (architectural prerequisite)
**Tier:** Cloud (vendor-hosted SaaS, deferred) — **not Enterprise**. Self-hosted Enterprise is single-tenant by design (reframed 2026-04-30 — see `docs-internal/GTM/free-vs-enterprise.md` §3).

No tenant-scoping infrastructure exists today — `User` has no tenant column, all catalog tables sit in single `catalog` schema, no request-context middleware. Required before the future **Cloud (multi-tenant SaaS) tier** can launch — vendor-operated deployment hosting many customer orgs with isolated data, users, audit, billing, and quotas. Touches identity, catalog, audit, and embed-token domains; needs migration plan + query-injection callback registry + tenant-context propagation. **Priority:** blocks Cloud launch, not next Enterprise sale.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.13: Persistent connector registry (BACKLOG — P2)

**Goal:** Greenfield Enterprise-tier feature — `Connector` ORM (id, type, config_jsonb, schedule, last_sync_at, owner_id) + `ConnectorAdapter` Protocol + Celery beat scheduler integration + encrypted credential vault. Distinct from current stateless probes at `backend/app/modules/catalog/sources/adapters/{wfs,arcgis,stac,ogcapi}.py`.
**Source:** `oc-separation-audit-20260430-b.md` §2 Seam #8 (🔴) / §7 P2
**Estimated effort:** 2–3 weeks
**Tier:** Enterprise — stored credentials + scheduled mirroring is an explicit Enterprise paywall per `docs-internal/GTM/free-vs-enterprise.md` §6.

Plans:

- [ ] TBD

---

### Phase 999.14: Helm chart + AMI Packer pipeline (BACKLOG — P2)

**Goal:** Build a `deployment/` directory with Helm chart for K8s deployments + Packer template for AWS Marketplace AMI distribution. Phase 223 wired the `BillingExtension` for AMI metering, but there's currently no path to actually ship the AMI image to AWS Marketplace.
**Source:** `oc-separation-audit-20260430-b.md` §4 (HIGH severity — no `deployment/`, no Helm, no AMI pipeline) → confirmed unchanged in `oc-separation-audit-20260502.md` §4 (structural gap unchanged) / §7 P2 (action item #13)
**Estimated effort:** 1–2 weeks

Plans:

- [ ] TBD

---

### Phase 999.15: SBOM + signed image distribution (BACKLOG — P2)

**Goal:** Add SBOM generation (CycloneDX or SPDX) + Cosign-signed images to the deployment pipeline. Typical enterprise procurement gate.
**Source:** `oc-separation-audit-20260430-b.md` §4 finding #4 / §7 P2
**Estimated effort:** 1 week

Plans:

- [ ] TBD

---

### Phase 999.16: Extract geolens-schemas package (BACKLOG — P2)

**Goal:** Extract `backend/app/standards/{stac,ogc,dcat}/` schemas + validators into a standalone `geolens-schemas` PyPI package (Apache-2.0). Embedded today; persistent OSS-surface gap per audits since v13.1 close.
**Source:** `oc-separation-audit-20260430-b.md` §6 (FAIL — schema/validator package not extractable) → confirmed unchanged in `oc-separation-audit-20260502.md` §6.1 (still no `schemas/` or `validators/` dir) / §7 P2 (action item #12)
**Estimated effort:** 1 week
**Unblocks:** Schema-validator OSS adoption beyond GeoLens consumers; reusable wedge for FAIR-aligned tooling.

Plans:

- [ ] TBD

---
*Roadmap updated: 2026-05-27 — v1030 active milestone added (7 phases, 44 v1 requirements, 100% coverage)*
