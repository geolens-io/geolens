# Project Research Summary

**Project:** GeoLens — v1030 Map Builder Polish Sweep
**Domain:** Internal product polish on a mature, feature-rich PostGIS-native map builder (NOT greenfield)
**Researched:** 2026-05-27
**Confidence:** HIGH

## Bottom Line

**Don't add anything. v1030 is verification + closing concrete gaps on the existing v1026 reconciler / v1027 action-boundary / v1008 unified-stack substrate.** No new libraries, no new architectural abstractions, no transport-layer rewrites. The audit-first Phase 1133 walkthrough produces the only ground-truth list of which polish items are still real — several `todo.md` items may already be closed by v1011/v1028, and several "easy wins" are known-pattern fixes within existing seams. The single new structural piece across the entire milestone is a thin staging layer above `dispatchLayerAction` for AI confirm-before-apply (Pitfall #3 — pick A or B upfront, do not mix).

The four research files converge on the same recommendation: extend existing contracts, do not introduce new ones. STACK says "use the existing libraries more idiomatically." FEATURES surfaces ~80 findings but 80%+ of the ADOPT list resolves to "verify the v1011/v1028 fix is still live, then close any drift." ARCHITECTURE maps every polish concern to an exact file + symbol in the substrate. PITFALLS grounds 15 critical traps in concrete prior post-mortems (v1009.1 / v1010.2 / v1011 / v1028) and ties each to specific load-bearing invariants that polish work routinely violates.

The dominant risk is scope creep into architecture work (Pitfall #12) — polish exposes "obvious" structural issues that look like 1-day refactors but pull in 1-week subsystem rewrites. Mitigate by holding the explicit out-of-scope list (annotation/draw, LiDAR, "Render as Text", new LLM providers, architecture rewrites) at every phase entry.

## Key Findings

### Recommended Stack

**No additions, no version bumps.** Every dependency in `frontend/package.json` and `backend/pyproject.toml` is already at the right version for v1030. The polish lands on libraries already in use:

**Core technologies (all already in place):**
- `maplibre-gl@^5.24.0` + `@vis.gl/react-maplibre@^8.1.0` — map runtime; stay on v5.24 (final v5 release)
- `chroma-js@^3.2.0` + `react-colorful@^5.6.1` — color/data-viz substrate; do NOT migrate to OKLCH (no v1030 requirement)
- `@dnd-kit/core` + `/sortable` + `/utilities` — unified-stack DnD from v1008/v1009/v1011
- `radix-ui@^1.4.3` — Dialog/DropdownMenu/Switch/Sheet (load-bearing for builder UX)
- `anthropic>=0.87` + `openai>=2.0,<3` — native tool-use streaming in `streaming.py` works on current versions; do NOT bump SDKs during polish
- `sse-starlette>=3.3.2` — SSE transport for chat streaming
- `navigator.clipboard.writeText` — share/embed copy (HTTPS + localhost coverage is sufficient)

**Explicit do-NOT-add list** (per STACK): Vercel AI SDK (replaces transport for no gain), `qrcode.react`, `@vercel/og`/satori, `react-share`/Web Share polyfills, `chromakit`/`culori` (OKLCH), `copy-to-clipboard` shim, Anthropic/OpenAI Agent SDKs, new responsive frameworks.

### Expected Features

FEATURES surfaced 80+ findings across AI chat, sharing, per-render-mode editors, map polish, and easy-wins. Breakdown by tier:

**Must-fix bugs (Tier 1 — explicit todo.md regressions):**
- MAP-17 Delete layer fix (todo.md line 146) — broken-on-live-map regression
- MAP-18 Regular layer visibility toggle (todo.md line 143) — broken-on-live-map regression
- MAP-16 Rename group focus (todo.md line 145) — trivial focus mgmt
- MAP-07/08/09/10 Smaller-screen layout collisions (todo.md lines 147-149) — partially closed by v1011, needs verify+complete
- MAP-19 Map scroll prevention (todo.md line 136)
- MAP-20 Filter pills vs. measure widget (todo.md line 103)

**Per-render-mode editor table stakes (Tier 2):**
- `RasterEditor.tsx` is a stub — Brightness/Contrast/Saturation/Hue + Reset (EDITOR-RASTER-01..04) is the single biggest one-file win
- LineEditor missing `line-cap` and `line-join` (EDITOR-LINE-01/02) — universal cartographic controls
- FillEditor height-column range hint (EDITOR-FILL-04)
- EDITOR-BASEMAP-02 "No basemap" preset + EDITOR-BASEMAP-03 remove DETAIL LEVEL toggle

**AI chat polish (Tier 3):**
- AI-01 Confirm-before-apply for destructive actions (todo.md line 108)
- AI-08 Data analysis inline card (todo.md line 171) — already-existing `show_query_result` action shape
- AI-09 Action preview chips ("what changed")
- AI-05 Selected-layer-aware suggestion chips

**Share polish (Tier 4) — builds on `3ed5ceb3`:**
- SHARE-02 Origins-as-chips after Save (visibility)
- SHARE-04 Expiration presets (1d/7d/30d/1y/Never)
- SHARE-07 "Powered by GeoLens" branding (todo.md line 151) + SHARE-09 legend+title in export
- SHARE-03 Iframe preview pane (if sandbox/sanitization straightforward)

**Easy-wins (Tier 5):**
- EASY-02 Cmd/Ctrl+S = Save (universal)
- EASY-11 Popup URL/media handling (todo.md lines 96 + 163)
- EASY-18 Empty-layer state ("0 features — check your filter")
- MAP-22/EASY-22 Notes indicator (todo.md line 101)

**Defer (out of scope for v1030):**
- SHARE-08 OG-image / social-card meta (depends on capture-pipeline scoping; flag v1031)
- EASY-07 Layer thumbnails (cost > benefit)
- EDITOR-RASTER-03 Stretch/colormap UI for single-band rasters
- EDITOR-FILL-01 `fill-pattern` (sprite upload flow too big)
- EDITOR-DEM-04/05 Contour lines + hypsometric tint
- All Anti-features (AI-A1..A4 inline editor / multi-turn-approve / model-picker / named convos; SHARE-A1..A4 per-viewer-auth / collaborator presence / public directory / password protection)

### Architecture Approach

The substrate has three load-bearing seams. Every v1030 polish item plugs into one of them — no new abstractions required:

1. **`BuilderLayerAction` union** (`builder-action-contract.ts`) — typed discriminated union, the only mutation entry point. Manual UI and AI chat share this contract.
2. **`LayerAdapter` interface** (`layer-adapters/*-adapter.ts`) — per-render-mode MapLibre behavior with `addLayers`/`syncPaint`/`syncVisibility`/`getLayerIds`. Each adapter declares `*_OWNED_PAINT_PROPERTIES` for the v1026 reconciler.
3. **`useBuilderEditorScene` / `editorLayer` / `editorScene`** (`use-builder-editor-scene.ts`) — panel routing for editor scenes.

**Single new structural piece across the milestone:** `frontend/src/components/builder/chat-action-staging.ts` — a thin staging layer above `dispatchLayerAction` for AI confirm-before-apply. This sits ABOVE the v1027 boundary; the boundary itself is unchanged.

**Major components touched:**
1. `frontend/src/components/builder/` (editors, panels, action contract, map-sync, layer-adapters) — bulk of polish
2. `backend/app/processing/ai/` (`tools.py`, `chat_actions.py`, `streaming.py`) — minor extensions only (optional `position` on `add_layer`)
3. `backend/app/modules/catalog/maps/router.py` — share/embed/access endpoints (small extensions to `3ed5ceb3`)

### Critical Pitfalls

The 15 pitfalls in PITFALLS.md ground in concrete prior post-mortems. Top 5 by likelihood-and-impact:

1. **Bypassing v1027 typed action boundary (Pitfall #1)** — A new AI chat action gets wired by calling `handleAddDataset()` directly from `ChatPanel.handleChatAction()` instead of dispatching through `BuilderLayerAction`. Provenance lost, dirty-state breaks, reconciler diverges. **Avoid:** Phase 1133 audit enumerates every existing switch case; planner guardrail requires `builder-action-contract.ts` edit whenever `ChatPanel.tsx` adds a new `action.type`.
2. **Collapsing v1026 patch/replace/clear tri-state (Pitfall #2)** — Polish to an editor or chat action treats paint as object merge, losing the `clear_paint` branch. Bug appears only after save → reload → reapply. **Avoid:** All paint mutations route through `buildChatActionPaint` (chat) or `syncOwnedPaintProperties` (editor); save/reload symmetry vitest per render mode mandatory.
3. **AI confirm-before-apply collapses snapshot/undo contract (Pitfall #3)** — Mixing "preview by applying" with "reject via undo" leaves half-applied state mid-stream. The v1027 boundary was designed for commit-immediately. **Avoid:** Pick shape A (pre-apply + atomic undo, requires `BuilderActionSource` widening) OR shape B (separate `pendingLayers` staging) BEFORE plan-01. Regression test: "rejecting leaves layers byte-equal to pre-prompt."
4. **AI provider-disabled state regresses (Pitfall #4)** — New AI hook gated only via mount-level `useAIStatus`, misses consumer-side `{ enabled: !!token && aiEnabled }` (v1010.2 SF-06 pattern). **Avoid:** Phase 1133 produces a consumer-gating matrix; close-gate Playwright MCP runs with `AI_ENABLED=false`.
5. **SharePanel raw-token cleared on dialog re-render (Pitfall #6)** — Polish "tidies up" `setRawShareToken(null)` on dialog close, breaking the v1011 SP-09 / `3ed5ceb3` survival contract. **Avoid:** Docstring at `useState` declaration; pin survival test in `SharePanel.test.tsx`.

Also load-bearing: Pitfall #10 (smaller-screen NavigationControl move re-creates v1011 RESP-02 800px overlap) — fix the sidebar collapse trigger, not nav position; Pitfall #12 (polish-sweep scope creep into architecture) — hard rule: no new files >500 LOC, no rename of >3 exported symbols.

## Implications for Roadmap

The ARCHITECTURE research recommends a 7-phase structure (1133-1139). FEATURES MVP organizes the same work into 5 Tiers (bugs → editors → AI → share → easy-wins). **Recommend the ARCHITECTURE 7-phase structure** because: (a) phase-numbering continues from 1133 per PROJECT.md (line 30), (b) audit-first sequencing is hard precedent (v1019/v1020/v1021/v1027/v1028 ALL ran audit-first), (c) FEATURES tiering is a priority view INSIDE phases, not a parallel phase structure. Tier-1 bugs land in Phase 1134, Tier-2 editor parity in 1136, Tier-3 AI in 1135, etc.

### Phase 1133: Audit-First Walkthrough
**Rationale:** Substrate is mature (v1026/v1027/v1008/v1028 all shipped); we don't know which polish items are still real. Several `todo.md` items may already be closed (Pitfall #13). Live Playwright MCP sweep is the only ground truth. Hard precedent: v1019/v1020/v1021/v1027/v1028 ALL spike-first.
**Delivers:** `BUILDER-WALKTHROUGH-AUDIT.md` triaged P0/P1/P2 with 15-min spike per "easy-win" before scheduling. Cross-references each `todo.md` item against milestone history. Produces consumer-gating matrix for all AI endpoints (Pitfall #4). Verifies v1027/v1026 contracts intact on `main` post-`3ed5ceb3`.
**Addresses:** Pitfall #13 (easy-wins turn hard), Pitfall #4 matrix prep, Pitfall #12 scope-creep guardrails
**Avoids:** Scheduling already-closed items; mis-attributing baseline behavior

### Phase 1134: Map Functionality Polish (Tier-1 bugs)
**Rationale:** Lowest blast radius (CSS scoping, focus refs, single-line adapter fixes). Closes regressions that block UAT. Phase 1135 (AI) depends on `dispatchLayerAction` being stable post-1134.
**Delivers:** MAP-17 delete-layer fix, MAP-18 visibility-toggle fix (likely adapter `syncVisibility` initial-layout gap — v1011 BUG-01 pattern), MAP-16 rename-group focus (rAF-deferred per v1011 BUG-03), MAP-07/08/09/10 smaller-screen layouts (verify v1011 fixes still live), MAP-19 map-scroll prevention, MAP-20 filter-pills positioning.
**Uses:** v1011 `data-builder-canvas` scoped-CSS pattern, v1011 sortable `disabled: { droppable }` per-drag-source contract
**Avoids:** Pitfall #10 (do NOT move NavigationControl back to `top-right` — fix sidebar collapse instead), Pitfall #11 (every new `<SheetContent>` opts out of duplicate X)

### Phase 1135: AI Chat Polish — MUST follow 1134
**Rationale:** Depends on `dispatchLayerAction` boundary being stable post-1134. The one new structural piece (`chat-action-staging.ts`) sits ABOVE the dispatch boundary, but tests in `ChatPanel.test.tsx` rely on synchronous dispatch after each `'actions'` event.
**Delivers:** AI-01 confirm-before-apply (CONTEXT.md picks shape A or B FIRST), AI-08 data-analysis inline card (extends existing `show_query_result`), AI-09 action preview chips, AI-05 viewport-aware suggestion chips, AI-02/03 verify disabled/error empty states.
**Implements:** `chat-action-staging.ts` module + extended `add_layer` tool with optional `position` + `style_hint`. NO new backend route; NO new BuilderLayerAction variants beyond `add_dataset` extensions in ARCHITECTURE Q1.
**Avoids:** Pitfall #1, Pitfall #2 (extend `buildChatActionPaint` test table), Pitfall #3 (pick A or B upfront — DO NOT mix), Pitfall #4 (every new hook gated on `enabled: !!token && aiEnabled`), Pitfall #5 (visibility filter + cache-key `(map_id, dataset_id)` + grep ban on `settings.*_api_key`)

### Phase 1136: Per-Render-Mode Editor Polish (parallel to 1135)
**Rationale:** Independent of AI work — editor controls don't touch chat. Can start as soon as 1134 ships. Self-contained per editor — each polish is a 1-3 file PR (editor + adapter owned-props + i18n key).
**Delivers:** EDITOR-RASTER-01..04 (biggest single-file win — RasterEditor is currently a stub), EDITOR-LINE-01/02 (line-cap, line-join — LAYOUT not PAINT properties), EDITOR-FILL-04 (height column range hint), EDITOR-BASEMAP-02/03 (no-basemap preset + remove DETAIL LEVEL), EDITOR-DEM-01/02 verify, EDITOR-HEAT-01 verify.
**Uses:** v1026 `*_OWNED_PAINT_PROPERTIES` / `*_OWNED_LAYOUT_PROPERTIES` extension pattern; v1010 `coalesceFrame` + 100/200ms debounces (do NOT bypass — Pitfall #9)
**Avoids:** Pitfall #2 (save/reload symmetry vitest per render mode), Pitfall #9 (grep guard forbidding `map.setPaintProperty` outside `layer-adapters/` + `map-sync.ts`)

### Phase 1137: Sharing/Embed Polish (independent — can parallel 1135/1136)
**Rationale:** Independent of all other work. Builds on `3ed5ceb3` `rawShareToken` vs `persistedShareTokenHint` separation. Thumbnail-surface depends on capture-thumbnail working — verify in Phase 1133 audit first.
**Delivers:** SHARE-02 origins-as-chips post-Save, SHARE-04 expiration presets, SHARE-07 "Powered by GeoLens" + SHARE-09 legend+title in export (`useEdition()` exists), SHARE-03 embed-preview iframe (if sandbox straightforward; else flag v1031), SHARE-05/06 verify status banner.
**Avoids:** Pitfall #6 (raw-token-survives-rerender pin), Pitfall #7 (`inflightEmbedCreate` ref mirrors ChatPanel pattern), Pitfall #8 (round-trip canonical-form vitest on PATCH `allowed_origins` + CSP no-wildcard backend pin), Pitfall #15 (CHANGELOG entry for shape change)

### Phase 1138: Easy-Win Sweep
**Rationale:** Catches items that don't fit any specific bucket — Cmd/Ctrl+S, popup URL/media, empty-layer state, Notes indicator, small i18n fixes, minor a11y wins from audit.
**Delivers:** EASY-02 Cmd/Ctrl+S, EASY-11 popup URL/media (PopupConfigEditor + popup-renderer), EASY-18 empty-layer state, MAP-22/EASY-22 Notes indicator.
**Avoids:** Pitfall #14 (live MCP per phase — no "small CSS-only change" exception)

### Phase 1139: Close-Gate
**Rationale:** Playwright MCP re-verify, `e2e:smoke:builder`, `npm run lint`, full vitest, i18n parity, CHANGELOG. v1027/v1028/v1029 hard precedent.
**Delivers:** Live MCP at 1440px/800px/414px, disabled-AI smoke (`AI_ENABLED=false`), OpenAPI/types diff vs CHANGELOG verify, CHANGELOG `[Unreleased]` populated.
**Avoids:** Pitfall #14 (skip live MCP), Pitfall #15 (CHANGELOG miss for contract changes)

### Phase Ordering Rationale

- **Audit-first (1133) is hard precedent** — v1019/v1020/v1021/v1027/v1028 all ran audit-first
- **1134 before 1135** — AI dispatch depends on `dispatchLayerAction` stability; adapter visibility-toggle fix may shift the boundary
- **1135 || 1136 || 1137 can run in parallel** — independent surfaces (chat ≠ editors ≠ share)
- **1138 catches the long tail** — without forcing items into a previous phase
- **1139 close-gate is canonical** — Playwright MCP + smoke + i18n + CHANGELOG

### Alternative: FEATURES 5-Tier Variant

FEATURES.md proposes a 5-Tier MVP organization (Tier-1 bugs / Tier-2 editor table stakes / Tier-3 AI / Tier-4 share / Tier-5 easy-wins). **Recommend ARCHITECTURE 7-phase structure over this** because:
- Phase numbering must continue from 1133 (PROJECT.md line 30) — Tier 1-5 is not a phase structure
- Tiers map cleanly onto phases: Tier-1 → 1134, Tier-2 → 1136, Tier-3 → 1135, Tier-4 → 1137, Tier-5 → 1138, with audit (1133) + close-gate (1139) bracketing
- ARCHITECTURE's audit-first phase is load-bearing — FEATURES tiering omits it
- ARCHITECTURE explicitly flags parallelism (1135 || 1136 || 1137 after 1134), which linear tier list does not

Treat the FEATURES tiering as the **priority view INSIDE phases**, not as the phase structure itself.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1133:** This IS the research — live Playwright MCP sweep produces all downstream phase scoping. No prior research-phase needed.
- **Phase 1135 (AI):** Confirm-before-apply shape decision (A vs B) needs explicit CONTEXT.md write-up BEFORE plan-01. Pitfall #3 is non-negotiable.
- **Phase 1137 (Sharing):** SHARE-08 OG-cards depends on capture-pipeline scoping — Phase 1133 audit verifies; if no 1200×630 variant, flag for v1031.

Phases with standard patterns (no research-phase needed):
- **Phase 1134:** All fixes are known-pattern (v1011 BUG-01 / BUG-03 / RESP-01..03 / CTRL-01)
- **Phase 1136:** Per-editor polish is "extend existing seam" — v1026 owned-property recipe covers every change
- **Phase 1138:** Easy-wins individually small enough to absorb without research
- **Phase 1139:** Close-gate pattern is canonical

### Critical Cross-References (FEATURES findings ↔ PITFALLS recovery patterns)

- **EDITOR-RASTER-01..04** MUST respect Pitfall #2 (v1026 patch/replace/clear) — every slider routes through `setPaint` via action handler; do NOT use `map.setPaintProperty` directly (Pitfall #9). Save/reload symmetry vitest mandatory.
- **EDITOR-LINE-01/02** — line-cap/line-join are LAYOUT not PAINT properties; ensure LineAdapter extends `*_OWNED_LAYOUT_PROPERTIES` (not paint). Same v1026 reconciler contract.
- **AI-01** confirm-before-apply — see Pitfall #3 (snapshot/undo collapse); CONTEXT.md MUST pick shape A or B upfront.
- **AI-08** data analysis card — see Pitfall #5 (cache leak / visibility leak / key leak) — visibility filter on `_validate_chat_layers` mandatory; cache key MUST be `(map_id, dataset_id)`; ESLint ban on `settings.*_api_key` interpolation.
- **AI-09** action chips — depends on AI-01; same staging-shape decision applies.
- **SHARE-02** origins-as-chips — see Pitfall #8 (allowed-origins UX regression); round-trip vitest on PATCH path; CSP no-wildcard backend pin.
- **SHARE-03** iframe preview — see Pitfall #8; iframe sandbox MUST stay `allow-scripts` only (no `allow-same-origin` — SEC-07 / M-70 at `SharePanel.tsx:36`).
- **SHARE-07/09** Powered-by + legend+title in export — `useEdition()` exists (`SharePanel.tsx:11,322`); verify viewer + ViewerMap + thumbnail-capture paths all read it; CHANGELOG entry mandatory.
- **MAP-07/08/09** smaller-screen layouts — see Pitfall #10 (NavigationControl move) + Pitfall #11 (`<SheetContent>` double-X); fix sidebar collapse trigger, NOT nav position.
- **MAP-18** visibility toggle — likely adapter `syncVisibility` initial-layout regression in one or more render modes (v1011 BUG-01 pattern recurs); audit ALL adapters not just the named one.

### Reconciling Open Questions (FEATURES 5 + ARCHITECTURE 4 = 9 → 5 unique surfaces)

| Surface | Source | Route to | Resolution |
|---------|--------|----------|------------|
| Confirm-before-apply staging shape (A vs B) | FEATURES AI-01 + ARCHITECTURE Q1/Q4 | Phase 1135 CONTEXT.md | Pick before plan-01 — Pitfall #3 |
| Categorical icon mapping with real distinct-values | FEATURES EDITOR-SYMBOL-04 + ARCHITECTURE Q4 | Phase 1133 audit | Check if `useColumnDistinctValues` hook exists; ADOPT or defer |
| OG-image / social-card depends on capture pipeline | FEATURES SHARE-08 + ARCHITECTURE Q3 | Phase 1133 audit | Verify 1200×630 thumbnail; if no, flag v1031 |
| Custom basemap style URL override | FEATURES EDITOR-BASEMAP-06 + ARCHITECTURE Q5 | DEFER v1031 | Architecture-shaped; out of scope |
| "Render as Text" layer type | FEATURES anti-feature + ARCHITECTURE Q4 | DEFER explicitly | OUT OF SCOPE per PROJECT.md line 35 |

Net: 5 unique decisions. 1 needs CONTEXT.md before plan (1135 AI shape). 3 routed to Phase 1133 audit. 2 deferred to v1031.

### Explicit Out-of-Scope (per PROJECT.md line 35) — DO NOT pull in

- Annotation / draw layer
- LiDAR support
- "Render as Text" / "Text as a layer type" (defer to v1031+ unless trivially scoped during easy-win pass)
- New LLM provider integrations
- New connector backends
- Builder architecture rewrites
- Marketing / docs site work
- Enterprise edition changes
- Large new feature builds

These surfaces, if discovered during the audit, get tracked as **v1031 carry-forwards in REQUIREMENTS.md**, NOT absorbed into v1030.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Read from `frontend/package.json` + `backend/pyproject.toml` directly; no version-bump = low compatibility risk |
| Features | HIGH | Substrate confirmed by code-read (ChatPanel, SharePanel, every LayerStyleEditor/, builder-action-contract, chat-suggestions); todo.md backlog cross-referenced |
| Architecture | HIGH | Every recommendation cites specific files + line numbers from substrate; no external research needed (PROJECT.md line 34) |
| Pitfalls | HIGH | All 15 pitfalls grounded in GeoLens source + concrete prior post-mortems (v1009.1 SP-09 / v1010.2 SF-04..08 / v1011 RESP-01..03 + CTRL-01 / v1028) |

**Overall confidence:** HIGH

### Gaps to Address

The audit-first Phase 1133 walkthrough is designed specifically to resolve these gaps. None blocks roadmap creation; all are deferrable to phase planning.

- **`useColumnDistinctValues` hook existence** — FEATURES EDITOR-SYMBOL-04 conditional. Resolve in Phase 1133 audit (15-min grep).
- **Thumbnail capture 1200×630 variant** — FEATURES SHARE-08 OG-cards depends. Resolve in Phase 1133 (verify `use-quicklook.ts` + autocaptured-map registry output sizes).
- **AI confirm-before-apply shape (A vs B)** — Pitfall #3 mandate. Resolve in Phase 1135 CONTEXT.md BEFORE plan-01.
- **`todo.md` staleness vs regression** — Several items (DETAIL LEVEL toggle, basemap draggable, layer toggle for specific map) may already be closed by v1011/v1028 OR may be regressions. Phase 1133 audit cross-references (Pitfall #13).
- **`3ed5ceb3` baseline behavior on `main`** — PROJECT.md line 29 confirms `3ed5ceb3` is now on `main`; Phase 1133 audit MUST run from clean `main` to avoid mis-attributing baseline (ARCHITECTURE Known Risks #2).

## Sources

### Primary (HIGH confidence)

- `frontend/package.json` (2026-05-27) — frontend deps verified
- `backend/pyproject.toml` (2026-05-27) — backend deps verified
- `frontend/src/components/builder/ChatPanel.tsx` — `ChatAction`, `handleChatAction`, `buildChatActionPaint`, `lastSnapshotRef`, `inflightRef` patterns
- `frontend/src/components/builder/SharePanel.tsx` — `rawShareToken`/`persistedShareTokenHint` separation post-`3ed5ceb3`; `parseOrigins`; embed-iframe sandbox contract (line 36)
- `frontend/src/components/builder/builder-action-contract.ts` — v1027 typed `BuilderLayerAction` union
- `frontend/src/components/builder/LayerStyleEditor/{Fill,Line,Circle,Symbol,Heatmap,Cluster,Raster}Editor.tsx` — per-render-mode editor substrate (RasterEditor confirmed stub)
- `frontend/src/components/builder/layer-adapters/{fill,line,circle,...}-adapter.ts` + `layer-adapters/shared.ts` — v1026 reconciler primitives
- `frontend/src/components/builder/hooks/use-builder-layers.ts` (lines 287, 721, 1124-1211) — `dispatchLayerAction`, `handleAddDataset`, `handleRemove`, `handleToggleVisibility`
- `frontend/src/components/builder/hooks/use-builder-editor-scene.ts` — editor scene controller
- `frontend/src/components/builder/map-sync.ts` (lines 293-361, 374, 451-467) — composition sync, `applyBasemapConfigToMap`, `reorderBasemapAboveData`, `getSourceIdForLayer`
- `frontend/src/components/builder/chat-suggestions.ts` — geometry-aware suggestion substrate
- `frontend/src/components/builder/MapToolbar.tsx` + `SettingsEditorScene.tsx` + `LayerEditorPanel.tsx` — builder UI surfaces
- `backend/app/processing/ai/streaming.py` (lines 103-234) — native Anthropic tool-use streaming
- `backend/app/processing/ai/{tools.py, chat_actions.py, schemas.py, chat_constants.py, router.py, tool_call_parser.py}` — AI tool contracts
- `backend/app/modules/catalog/maps/router.py` (lines 110, 473, 779-797, 863, 1316-1481) — share/embed/access endpoints, `_build_csp_frame_ancestors`
- `.planning/PROJECT.md` — v1030 scope, OUT-OF-SCOPE list (line 35), substrate references (v1026/v1027/v1029)
- `todo.md` lines 96-171 — current polish backlog
- `git show 3ed5ceb3` — in-flight share/access/chat polish (now on `main`)

### Secondary (MEDIUM confidence — version numbers / competitor surveys)

- MapLibre GL JS releases on GitHub — v5.24.0 confirmed final v5
- `@vis.gl/react-maplibre` on npm — v8.1.0 latest
- `anthropic-sdk-python` releases — v0.104.1 latest (no breaking since 0.87)
- OpenAI Python SDK on PyPI — v2.38.0 latest (2.0-3.0 still current)
- MapLibre Style Spec (raster paint properties, line layout properties)
- Felt / Atlas.co / Mapbox MapGPT / ArcGIS Map Viewer (June 2025) / kepler.gl / QGIS Cloud / MapBuilder (WRI) — competitive feature surveys
- Vercel AI SDK comparison guide — confirms transport-abstraction-only (no new capability)

### Tertiary (LOW confidence — relied on inference)

- "No breaking changes" for anthropic 0.87 → 0.104.1 — GitHub release notes don't enumerate breaking changes explicitly; major remains 0.x, code paths in `streaming.py` use stable Messages API surface
- Some `todo.md` items may be already-closed-but-rewritten in v1011/v1028 — Phase 1133 audit resolves

---
*Research synthesized: 2026-05-27*
*Bottom line: don't add anything; the milestone is verification + closing concrete gaps surfaced by the Phase 1133 audit.*
*Ready for roadmap: yes — recommend ARCHITECTURE 7-phase structure (1133 → 1134 → {1135 || 1136 || 1137} → 1138 → 1139); use FEATURES tiering as priority view inside phases.*
