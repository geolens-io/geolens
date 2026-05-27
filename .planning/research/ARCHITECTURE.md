# Architecture Research — v1030 Map Builder Polish Sweep

**Domain:** Internal product polish for the GeoLens map builder (feature-rich layered authoring surface).
**Researched:** 2026-05-27
**Mode:** Project research (integration-only, no ecosystem survey).
**Substrate baseline:** v1008 unified stack, v1026 style reconciler, v1027 controller + typed action boundary, v1029 DCAT 3.0, in-flight share/access/chat polish at `3ed5ceb3`.

---

## Executive Summary

v1030 is a **polish + audit milestone** layered on top of an already-shipped substrate: a typed `BuilderLayerAction` contract (`builder-action-contract.ts`), a `dispatchLayerAction` bridge wired into both manual UI and AI chat (`use-builder-layers.ts:1124`), an editor-scene controller (`use-builder-editor-scene.ts`), per-render-mode editor components dispatched by a lookup table (`LayerStyleEditor/RenderModeSwitch.tsx`), and per-render-mode MapLibre adapters with owned-property reconciliation (`layer-adapters/shared.ts`).

The architecture-level question for v1030 is **NOT "what new abstractions do we need?"** — it's **"where do new behaviors plug into existing seams without violating contracts?"**

Three clean seams already exist:
1. **`BuilderLayerAction` union** for any mutating intent (manual, AI, system).
2. **`LayerAdapter` interface** for any per-render-mode MapLibre behavior.
3. **`useBuilderEditorScene` / `editorLayer` / `editorScene`** for any panel routing.

For each of the six v1030 polish questions, **the answer is plug into existing seams**, with one exception (AI confirm-before-apply staging) that needs a thin new layer above `dispatchLayerAction`.

The recommended phase order is:
1. **Audit-first walkthrough** (writes BUILDER-WALKTHROUGH-AUDIT.md — no code).
2. **Map functionality polish** (small-screen layout, dirty/save, settings/widgets — low blast radius, unblocks UAT).
3. **Per-render-mode editor polish** (LineEditor/FillEditor/etc — extends adapters via existing owned-property protocol).
4. **AI chat polish** (creation + analysis — extends existing `add_layer` / `query_data` tools; the only new structural piece is an optional "confirm" gate).
5. **Sharing/embed polish** (extends `3ed5ceb3` separation; possibly adds embed-preview surface).
6. **Easy-win sweep + close-gate** (Playwright MCP + i18n + smoke).

---

## Q1. AI-chat layer creation — where does `create_layer` live?

### Current State (Verified)

- **Tool already exists.** `add_layer` is the LLM-facing tool (`backend/app/processing/ai/tools.py:294-309`) and lives in `_EDIT_TOOLS` (`chat_constants.py:16-25`). Its only required input is `dataset_id`.
- **Action already exists.** `ChatAction.type='add_layer'` is in the Pydantic union (`schemas.py:363-386`) with a `dataset_id` field.
- **Frontend dispatch already exists.** `ChatPanel.tsx:305-309` routes `add_layer` to `layerActions.onAddDataset(datasetId)`, which goes through `dispatchLayerAction({ type: 'add_dataset', source: 'ai', datasetId })` (use-builder-layers.ts:1194-1198) → `handleAddDataset` (use-builder-layers.ts:721).
- **Builder side handles insertion + default style** via `handleAddDataset` → `addLayerMutation` (server `POST /api/maps/{map_id}/layers`) → reducer prepends to `localLayers` → `useLayerMapSync` triggers the adapter for the inferred render mode.

### Gap (What "Layer creation" polish actually means)

The plumbing exists, but the user-flow polish gaps are:

| Gap | Where it lives | Polish opportunity |
|-----|----------------|-------------------|
| Insertion position (top vs bottom vs above selected) | `handleAddDataset` (use-builder-layers.ts:721+) | Currently inserts somewhere fixed; AI can't ask "below the roads layer" |
| Default style for the AI-created layer | adapter `addLayers` defaults + `MAP_COLORS.default` | A single style per geom type; AI can't pre-style on creation |
| Confirm-before-apply | None — every chat action applies immediately, with single-level Undo (`lastSnapshotRef`, ChatPanel.tsx:172) | User-facing polish: "I'm about to add 3 layers — proceed?" |
| Search → preview → add flow | `search_datasets` tool returns IDs; `add_layer` consumes one | Better surface in chat output for "I found 3 candidates — which one?" |

### Recommendation

**Do NOT introduce a new `create_layer` action.** Extend the existing `add_dataset` BuilderLayerAction with optional payload fields, and let the AI tool keep its `add_layer` name.

**Specific extensions (minimal, all in existing seams):**

1. **Insertion position** — extend `BuilderLayerAction['add_dataset']` to optionally carry `position: 'top' | 'bottom' | { aboveLayerId: string }`. Default stays "top" (existing behavior). Backend `add_layer` tool gets an optional `position` enum.
2. **Default style hint** — extend `add_dataset` action with optional `style_hint: StyleConfig | null`. `handleAddDataset` passes it to `addLayerMutation`. Reuses the v1026 reconciler — no new code path.
3. **Confirm-before-apply (THE one new structural piece)** — see Q4 below; this is cross-cutting, not creation-specific.

### Confirm-Before-Apply: Recommended Shape (Cross-cutting)

ChatPanel currently applies every action inside the streaming `actions` SSE event (ChatPanel.tsx:371-400). The cleanest place to gate is **the same `dispatchLayerAction` call site**, with a thin staging layer:

```text
streamChatMessage → 'actions' event → [STAGING REVIEW] → dispatchLayerAction(...)
```

**New (small) module:** `frontend/src/components/builder/chat-action-staging.ts`
- Exports `shouldStageAction(action: ChatAction): boolean` — returns true for `add_layer`, `remove_layer` (already non-undo-safe per ChatPanel.tsx:107-111), maybe `set_data_driven_style` if user setting is enabled.
- Exports `StagedActionsBanner` component — accepts/rejects a batch of pending actions inline in the chat message bubble.
- Does NOT touch backend; works on the existing `ChatAction[]` stream.
- Configurable via existing settings (read-only feature flag for v1030, or admin toggle).

**Crucially**, this is purely additive — when staging is OFF or the action is safe, the existing flow runs unchanged. The v1027 `dispatchLayerAction` boundary is unchanged.

---

## Q2. AI-chat data analysis — read-only flows

### Current State (Verified)

- **`query_data` tool already exists** (`tools.py:310-328`) and produces `show_query_result` actions (`chat_actions.py:243-250`) with `geojson` + `bbox`.
- **Frontend already handles it** via `dispatchQueryResult` (ChatPanel.tsx:208-227) → `onQueryResult` → `handleQueryResult` (use-ephemeral-layers.ts:107-109) → adds an ephemeral source `ephemeral-result` with 4 typed layers (polygon fill/outline, line, point) and auto-fits to bbox.
- **`search_datasets` tool already exists** (`tools.py:88-93`) — returns `id, title, summary, geometry_type, keywords, extent_bbox, feature_count, column_info, sample_values`.
- **Layer column context** — `ChatMapLayer` (schemas.py:316-333) carries `column_info`, `sample_values`, `feature_count`, `style_config`, `paint` per layer the user has active.

### Gap

The "which datasets cover Y" / "what's in this layer" prompts have the **plumbing**, but polish gaps:

| Gap | Where |
|-----|-------|
| Ephemeral layer naming/legend | `useEphemeralLayers` (use-ephemeral-layers.ts:1-117) has 4 fixed-style layers, no naming, no legend integration |
| Dismissal UX | `handleDismissEphemeral` exists but no inline button in chat bubble |
| Bbox spatial filter on `search_datasets` | Backend `bbox` param already accepted (tools.py:48-55); no chat-suggestion chip prompting it |
| Layer-shape reuse | Query result doesn't snapshot to a real layer (user can't promote ephemeral → permanent) |
| AOI-aware suggestions | `getSmartSuggestions` (chat-suggestions.ts) doesn't know map viewport |

### Recommendation

**No new action type. No new backend tool.** All polish is frontend-side:

1. **Dismiss/promote affordance** — add buttons inside the chat bubble for `show_query_result` actions: "Dismiss" (clears ephemeral) and (stretch goal) "Save as layer" (would need a new BuilderLayerAction `add_ephemeral_as_layer`; treat as v1031 stretch).
2. **Smart suggestions extension** — `getSmartSuggestions(layers, t)` already takes layers; extend to take the map viewport (or current bbox from `useBuilderLayers` saved center/zoom) and surface chips like "What datasets cover this view?"
3. **Ephemeral layer styling** — share the existing `MAP_COLORS` palette; consider extracting a tiny `getEphemeralLayerSpec(geometryType)` helper from the inline addLayer block.

**No new read-only action type is needed** because the existing `show_query_result` already carries arbitrary GeoJSON + bbox — that covers "which datasets cover Y" once the backend's `query_data` SQL generator is steered (which is a prompt/skill change, not an architecture change).

---

## Q3. Sharing/embed polish — where do `3ed5ceb3` changes point next?

### What `3ed5ceb3` Actually Landed (Verified)

The commit message + diff confirm:
- **New backend route `GET /api/maps/{map_id}/access/`** returning `{can_view, can_edit}` (router.py:779-797) so `MapViewerGate` no longer depends on the client-side `isAdmin`/role flag.
- **SharePanel separation** — `rawShareToken` (state, freshly-minted) vs `persistedShareTokenHint` (query data, server-side hint). The "regenerate to copy again" affordance when the raw token isn't in memory (SharePanel.tsx:622-647).
- **Embed-token regenerate** path when `activeEmbedToken` exists but `embedTokenRaw` was lost (SharePanel.tsx:451-466).
- **Save-state banner** — `share-output-save-state` test-id banner explaining how unsaved/saving/failed states interact with share links (SharePanel.tsx:512-541).

### Forward-Pointing Gaps

| Gap | Surface | Polish opportunity |
|-----|---------|---------------------|
| **Embed preview** | None — operator copies iframe to test | Side-by-side iframe preview inside ShareDialog |
| **OG-image / social preview** | `useUploadThumbnail` exists (use-maps.ts via `PUT /api/maps/{id}/thumbnail/`) but never surfaces in share | Show thumbnail in ShareDialog; let user regen |
| **Allowed-origins UX** | Comma-separated input (SharePanel.tsx:255-260) | Tag-style chips, origin validation, "add current parent origin" button |
| **Expiration UX** | Date picker only (SharePanel.tsx:199-206) | Quick presets (1 day / 1 week / 30 days / never), plus current behavior |
| **Embed-token list visibility** | `useMapEmbedTokens` returns array; only one is shown in summary | Per-token domain/expiration table for admins |
| **Viewer/embed parity** | `MapViewerGate` uses new access endpoint; sharing has no equivalent "what will viewer see?" preview | Pre-flight `visibility-check` already exists (router.py:500-518) — surface non-public layer names in the banner |
| **Copy-link → in-flight verification** | None — user copies, then must paste in a new tab to verify | A "Test link" button that opens an incognito-like check (could reuse `getSharedMap()` cross-origin probe) |
| **Frame-ancestors CSP** | `_build_frame_ancestors` exists (router.py:110) but not surfaced as a "policy" indicator in the embed section | Inline note: "This iframe will work on: example.com, app.example.com" |

### Recommendation

**Build on the rawToken/persistedHint separation pattern.** All polish is additive within existing `SharePanel.tsx`:

1. **Embed preview iframe** — render a sandboxed iframe of the current embed URL inside ShareDialog when a token is in memory.
2. **Thumbnail surface** — add `<img src={`/api/maps/${mapId}/thumbnail/`} />` near the share section.
3. **Allowed-origins chip input** — replace the comma string with a chip array, validate per `parseOrigins()` (already returns normalized strings).
4. **Expiration presets** — wrap the existing date input with preset buttons; pass through to existing `updateShareToken` mutation.
5. **Pre-flight banner** — use `checkMapVisibility` (already wired) to show "Note: 2 of your layers are private; viewers will need an embed token" with the actual non-public layer names.

**No new backend routes are required for any of the above** — every polish item maps to existing endpoints. (Possible exception: a list/manage embed-tokens admin surface, which already has `admin_router.py` per the grep above and can stay out of v1030 scope.)

---

## Q4. Per-render-mode editor polish — preserving the reconciler contract

### Current Architecture (Verified)

The v1026 + v1027 architecture has **three layers** of separation:

```text
┌─────────────────────────────────────────────────────────────────┐
│ LayerStyleEditor (UI)                                            │
│ └── RenderModeSwitch (lookup table)                              │
│     ├── FillEditor.tsx                                           │
│     ├── LineEditor.tsx                                           │
│     ├── CircleEditor.tsx                                         │
│     ├── SymbolEditor.tsx                                         │
│     ├── HeatmapEditor.tsx                                        │
│     ├── ClusterEditor.tsx                                        │
│     └── RasterEditor.tsx                                         │
│         All emit through BaseStyleEditorProps callbacks:         │
│         onPaintProp / onPaintChange / onLayoutChange /           │
│         onBuilderChange                                          │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼ (callbacks compose to BuilderLayerAction)
┌─────────────────────────────────────────────────────────────────┐
│ dispatchLayerAction (typed action boundary)                      │
│ └── BuilderLayerAction union: set_paint / set_style_config / ... │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ useLayerMapSync handlers → layer-adapters                        │
│ └── LayerAdapter:                                                 │
│     - addLayers(map, input)                                      │
│     - syncPaint(map, input)         [owned-property reconcile]   │
│     - syncVisibility(map, input)                                 │
│     - getLayerIds(layerId): string[]                             │
│   Per-adapter constant: *_OWNED_PAINT_PROPERTIES                 │
└─────────────────────────────────────────────────────────────────┘
```

The **load-bearing invariants** are:
- Editors emit through prop callbacks — they never poke the map.
- Editors read from `layer.paint` / `layer.style_config.builder` / `layer.layout` — single source of truth.
- Adapters declare `*_OWNED_PAINT_PROPERTIES` constants — `syncOwnedPaintProperties` (shared.ts:293-336) reconciles only those.
- Custom paint keys (anything in `CUSTOM_PAINT_PROPS`, shared.ts:6-13) are kept in `layer.paint` but stripped before sending to MapLibre via `stripCustomProps` / `filterPaintForLayerType`.
- Companion layers (outline, extrusion, arrow, label, cluster count/circle) are owned end-to-end by the adapter and surfaced via `getLayerIds(layerId)`.

### What "Easy Wins" Mean Here

Polish opportunities by editor (drawn from `todo.md` + structural inspection):

| Editor | Polish |
|--------|--------|
| **LineEditor** | Already has gradient + arrow + dash + offset. Polish: arrow direction (forward/reverse/both) — currently only forward; line-cap selector (round/square/butt) |
| **FillEditor** | Already supports outline + extrusion. Polish: better extrusion-3D enablement UI; "lock outline color to fill" toggle |
| **CircleEditor** | Polish: stroke-width slider parity with fill; cluster-mode handoff |
| **SymbolEditor** | Polish: sprite browser; icon-rotation control |
| **HeatmapEditor** | Polish: weight-column selector parity with column-driven styling |
| **ClusterEditor** | Polish: min-points threshold |
| **RasterEditor** | Polish: contrast/brightness/saturation parity with MapLibre raster paint props |
| **Cross-cutting** | "Render as Text" — explicitly OUT of scope for v1030 per PROJECT.md line 35. Defer. |

### Extension Recipe (Preserves v1026 Contract)

To add a control to LineEditor without breaking adapter contracts:

1. **If the control maps to a MapLibre paint property** (e.g., `line-cap`): edit the editor to add a `<SliderRow>` or `<Select>` that calls `onPaintProp('line-cap', value)`. Add `line-cap` to `LINE_OWNED_PAINT_PROPERTIES` in `line-adapter.ts` so the reconciler manages it. **Done — no new code paths.**
2. **If the control maps to a builder-only field** (e.g., a new arrow option): add to `BuilderStyleConfig` type, read in `getBuilderStyleConfig(input)` via the existing `BUILDER_STYLE_KEY_ALIASES` map (map-sync.ts:403), and consume in the adapter's `syncPaint`. **Done — no new action types.**
3. **If the control needs a new companion layer** (rare): extend the adapter's `addLayers` + `syncPaint` + `syncVisibility` + `getLayerIds`. The companion layer pattern (outline, extrusion, arrow) gives a reference.

### Recommendation

**Polish per editor in-place.** Each per-editor change is a 1-3 file PR (editor + adapter owned-props + i18n key). No new abstractions. No new architectural layer.

**The minimal extension point** for "Render as Text" specifically (out of v1030 scope but worth noting): would be a new `RenderAsId='text'` value in `renderAs.ts:4-16` + a new symbol-shaped adapter or shared symbol path with `text-field`-only paint. The `RENDER_AS_WRITABLE_FIELDS` + `buildRenderAsPatch` pattern already exists (renderAs.ts:82, 409) — adding a new render mode reuses that machinery. **Defer to v1031+.**

---

## Q5. Map functionality polish — controller integration

### Touchpoints (Verified)

| Polish item | Controller / Module |
|-------------|---------------------|
| Viewport preservation | `useBuilderSave` reads `map.getCenter/Zoom/Bearing/Pitch` (use-builder-save.ts:445-449) and writes to `MapUpdateRequest` |
| Dirty state | `setHasUnsavedChanges` lives in `useBuilderLayers` (use-builder-layers.ts:52, 65, 122). Every mutating handler calls `markDirty` or `setHasUnsavedChanges(true)`. |
| Save status | `useBuilderSave` returns `saveStatus: BuilderSaveStatus` (use-builder-save.ts:736-751). Already surfaced in `SharePanel` banner (SharePanel.tsx:512-541) |
| History | `HistoryPanel.tsx` reads `useMapHistory(mapId, 0, limit)` server-side; no undo/redo state in builder — just a read-only audit list |
| Settings/widgets | `useWidgetStore` zustand store (`stores/map-widget-store.ts`); `toggle(widgetId)` is called from MapBuilderPage:990. Widget host is `WidgetHost.tsx` |
| Basemap | `useBuilderLayers` owns `localBasemap` + `basemapConfig` + `showBasemapLabels` + `localTerrainConfig`. `applyBasemapConfigToMap` (map-sync.ts:317-361) reconciles. `reorderBasemapAboveData` (map-sync.ts:293-314) handles drag-orderable basemap position |
| Smaller-screen layouts (RESP-01..03 from v1011) | `BuilderMap` NavigationControl (`top-left`), `MapCoordReadout` (`right-14`), `data-builder-canvas="true"` scoped CSS rule — established in v1011 |

### Smaller-Screen Polish Items From `todo.md`

The `todo.md` lines 138-149 list these specific small-screen gaps:
- Right sidebar collapse overtops zoom controls.
- Lat/long pill overlays the map widget container.
- Basemap selector has two stacked "X" buttons.
- "Rename group" doesn't focus the text field.
- Delete layer doesn't work (regression — verify on `localhost:8080`).
- Layer 1 visibility toggle no-op on certain maps (regression — verify).
- "Detail level toggle" — kept disposition from v1011 (REMOVE; dead-wired).

### Recommendation

**Every item maps to an existing surface:**

1. **Small-screen layout collisions** — extend the v1011 pattern. The `data-builder-canvas` scoping is the precedent. Add ARIA + z-index discipline to right-sidebar collapse, lat/long pill, basemap selector.
2. **Rename-group focus** — `requestAnimationFrame(() => input.focus())` pattern; precedent in ChatPanel.tsx:542-544.
3. **Delete-layer regression** — likely in `handleRemove` (use-builder-layers.ts:287) or its companion-layer cleanup (`removePerLayerCompanions` in `builder-layer-mutations.ts`). Audit-first surfaces the exact failure mode.
4. **Visibility-toggle regression** — likely in `handleToggleVisibility` → adapter `syncVisibility` for some render mode that's missing initial-layout handling (cf. fill-adapter.ts:85-95 BUG-01 precedent: `initialLayout = visible === false ? { ...layout, visibility: 'none' } : layout`). Same shape regression may exist in another adapter.
5. **Widgets toggle redundancy question** (todo.md:144) — Settings → Widgets toggles control "is this widget mountable?", separate from the user's on-map widget controls. Polish opportunity: better copy + group widgets that are always-on (Navigation, Scale) vs toggleable (Measurement). UI-only.
6. **Save indicator** — already shipped in v13.11 QUALITY-01 (todo.md:105). Verify still working.
7. **Public map zoom-control location** — already shipped in v13.11 QUALITY-04 (todo.md:107). Verify regression-free.

**Recommended:** treat all of these as **bug-shape closures** in a single phase, gated by the audit-first walkthrough.

---

## Q6. Suggested Build Order for v1030

### Phase Dependency Graph

```text
[Audit-first walkthrough]   Phase 1133
        │ produces BUILDER-WALKTHROUGH-AUDIT.md
        ▼
        ├─────────────────────────────────────────┐
        ▼                                         ▼
[Map functionality polish]   Phase 1134    [Per-render-mode editor polish]   Phase 1136
  (small-screen, save/dirty,                 (per-editor easy wins;
   visibility/delete bug fixes)               adapter owned-props additions)
        │                                         │
        │                                         │
        ▼                                         ▼
[AI chat polish]   Phase 1135              [Sharing/embed polish]   Phase 1137
  (build on dispatchLayerAction;             (build on 3ed5ceb3 separation;
   add staging for non-undo-safe;            embed preview, OG image,
   smart suggestions w/ viewport)            allowed-origins chips)
        │                                         │
        └────────────────┬────────────────────────┘
                         ▼
              [Easy-win sweep]   Phase 1138
                (close low-cost items from
                 audit + todo.md backlog)
                         │
                         ▼
              [Close-gate + Playwright MCP]   Phase 1139
                (smoke + i18n + final re-verify
                 + CHANGELOG)
```

### Rationale

| Phase | # | Why this order |
|-------|---|----------------|
| **Audit-first walkthrough** | 1133 | Substrate is mature; we don't know which polish items are still real (some may already be fixed). Live MCP sweep produces the only ground truth. **Hard precedent:** v1019/v1020/v1021/v1022 (4 spike-first milestones in a row), v1027 audit baseline, v1028 workflow audit. |
| **Map functionality polish** | 1134 | Lowest blast radius (CSS scoping, focus refs, single-line adapter fixes). Closes the regressions that block UAT for everything else. |
| **Per-render-mode editor polish** | 1136 | Parallel to AI work (no overlap — editor controls don't touch chat). Can start as soon as 1134 ships. Self-contained per editor. |
| **AI chat polish** | 1135 | Depends on the dispatchLayerAction surface being stable (1134 might touch removePersistedLayer / removeDraftLayer). The one new module (`chat-action-staging.ts`) sits ABOVE dispatchLayerAction. |
| **Sharing/embed polish** | 1137 | Independent of all the above. Builds on the 3ed5ceb3 separation pattern. The thumbnail surface depends on capture-thumbnail working — verify in audit phase first. |
| **Easy-win sweep** | 1138 | Catches the items that don't fit any specific bucket (small i18n fixes, lint fixes, minor a11y wins from audit). |
| **Close-gate** | 1139 | Playwright MCP re-verify on `localhost:8080`, `e2e:smoke:builder`, `npm run lint`, full vitest, i18n parity, CHANGELOG. v1027/v1028/v1029 precedent. |

### Parallelism

After Phase 1133 (audit), Phases 1134 / 1136 / 1137 are **independent and can run in parallel** if multiple executors are available. Phase 1135 (AI chat) **must follow 1134** because the dispatch boundary may shift slightly.

### Out of Scope (Per PROJECT.md line 35)

- "Render as Text" layer type — defer to v1031+ as a `RenderAsId` extension.
- Annotation/draw layer.
- LiDAR support.
- New LLM provider work.
- New connector backends.
- Enterprise edition changes.

These items, if surfaced during the audit, should be **tracked as v1031 carry-forwards in REQUIREMENTS.md** rather than absorbed into v1030.

---

## Integration-Point Cheat Sheet

For executors/synthesizer reference — exact files and functions per polish concern:

| Concern | Type | File | Symbol |
|---------|------|------|--------|
| Add `add_dataset` extensions | MODIFIED | `frontend/src/components/builder/builder-action-contract.ts` | `BuilderLayerAction` union (line 19) |
| Add staging gate for AI actions | NEW | `frontend/src/components/builder/chat-action-staging.ts` | `shouldStageAction`, `<StagedActionsBanner>` |
| Wire staging into chat | MODIFIED | `frontend/src/components/builder/ChatPanel.tsx` | `handleChatAction` / streaming `'actions'` case (line 371) |
| Add `position` to `add_layer` tool | MODIFIED | `backend/app/processing/ai/tools.py` | `_ADD_LAYER` schema (line 294) |
| Pass `position` to handler | MODIFIED | `backend/app/processing/ai/chat_actions.py` | `_collect_chat_action` (line 236) |
| Insertion position in handler | MODIFIED | `frontend/src/components/builder/hooks/use-builder-layers.ts` | `handleAddDataset` (line 721) |
| Ephemeral layer naming | MODIFIED | `frontend/src/components/builder/hooks/use-ephemeral-layers.ts` | `addLayers` IIFE (line 37) |
| Smart suggestions w/ viewport | MODIFIED | `frontend/src/components/builder/chat-suggestions.ts` | `getSmartSuggestions` |
| Embed preview iframe | MODIFIED | `frontend/src/components/builder/SharePanel.tsx` | After embed code textarea (line 720) |
| Thumbnail in share | MODIFIED | `SharePanel.tsx` | Inside `<DialogContent>` after visibility selector |
| Allowed-origins chip input | MODIFIED | `SharePanel.tsx` | `ShareLinkSettings` domain section (line 221) |
| Per-editor controls | MODIFIED | `frontend/src/components/builder/LayerStyleEditor/{Line,Fill,Circle,...}Editor.tsx` | Each editor's `<>` body |
| Per-adapter owned props | MODIFIED | `frontend/src/components/builder/layer-adapters/{line,fill,circle,...}-adapter.ts` | `*_OWNED_PAINT_PROPERTIES` constants |
| Small-screen CSS scoping | MODIFIED | `frontend/src/components/builder/BuilderMap.tsx` + global CSS | `data-builder-canvas` attribute (v1011 precedent) |
| Visibility/delete regressions | MODIFIED | `use-builder-layers.ts` `handleRemove` (line 287), `handleToggleVisibility`; adapter `syncVisibility` per render mode | — |
| Widget store integration | NO CHANGE | `frontend/src/stores/map-widget-store.ts` | `useWidgetStore` (settings polish is UI-only) |

---

## v1026 / v1027 / v1008 Contract Preservation

The following invariants **MUST be preserved**:

| Contract | Source | Why load-bearing |
|----------|--------|------------------|
| `BuilderLayerAction` is the only mutation entry point | `builder-action-contract.ts` | AI chat + manual UI share this — drift causes diverging behavior |
| Adapters own their MapLibre paint/layout via `*_OWNED_PAINT_PROPERTIES` | `*-adapter.ts` per render mode | Anything outside the ownership set is preserved as user-style; reconciler scope discipline |
| `useBuilderEditorScene` derives `editorScene` from `expandedLayerId` + `editingLayer.is_dem` | `use-builder-editor-scene.ts:12-22` | Synthetic basemap/settings/dem layer descriptors flow from this; new scenes need a new branch + synthetic factory |
| `dispatchLayerAction` is the only place that translates a `BuilderLayerAction` to handler calls | `use-builder-layers.ts:1124-1160` | Adding a new action type means: type union update + handler table update + chat dispatcher coverage in `ChatPanel.handleChatAction` |
| `CUSTOM_PAINT_PROPS` strip happens before any MapLibre call | `shared.ts:6-13` + `stripCustomProps` | Builder-only fields (`_outline-width`, `_height_column`) leaking to MapLibre = console errors |
| Source-id dedupe via `getSourceIdForLayer` | `map-sync.ts:451-467` | Phase 1050 SF-04 contract — non-cluster vector layers share sources per `dataset_table_name`. Polish must NOT add per-layer sources for non-cluster vector layers. |
| `_add_trailing_slash_aliases(app)` covers ~72 routes | `backend/app/api/main.py:443-487` (Phase 1092 ROUTE-01) | Any new share/embed/access route should use the same dual-shape registration |

**Phase 1133 audit MUST verify these contracts are still respected on `main`.**

---

## Known Risks for v1030

1. **Visibility/delete regression** (todo.md:143, 146) — if it's adapter-level, the fix may apply across multiple adapters (fill, line, circle, raster). The v1011 BUG-01 precedent (initialLayout) suggests this pattern recurs.
2. **`3ed5ceb3` changes are uncommitted on the branch** (per git status — files modified but not yet pushed). Phase 1133 audit must run **after** that commit lands on `main`, or the audit will mis-attribute baseline behavior.
3. **Confirm-before-apply scope creep** — easy to expand into a full action history / multi-step undo stack. Hold the line: gate at `dispatchLayerAction` for non-undo-safe actions only; reuse existing `lastSnapshotRef` single-level undo for everything else.
4. **Smaller-screen layout** at <800px is in the v1011-established `data-builder-canvas` scope. New polish must NOT introduce ungated CSS that affects ViewerMap (separate component).
5. **AI chat staging UX** changes the action-application timing — tests in `ChatPanel.test.tsx` rely on synchronous `dispatchLayerAction` calls after each `'actions'` event. New tests required.
6. **i18n parity** — every user-visible string change must add keys to all 4 locales (en/de/es/fr) — v1009 precedent (770-key parity).

---

## Sources

- `backend/app/processing/ai/tools.py` (chat tool schemas) — verified HIGH
- `backend/app/processing/ai/schemas.py` (ChatAction, ChatMapLayer) — verified HIGH
- `backend/app/processing/ai/chat_constants.py` (_EDIT_TOOLS) — verified HIGH
- `backend/app/processing/ai/chat_actions.py` (action collection) — verified HIGH
- `backend/app/modules/catalog/maps/router.py:1316-1481` (share endpoints) — verified HIGH
- `backend/app/modules/catalog/maps/router.py:779-797` (access endpoint, Phase 3ed5ceb3) — verified HIGH
- `frontend/src/components/builder/ChatPanel.tsx` (action dispatch) — verified HIGH
- `frontend/src/components/builder/SharePanel.tsx` (share UI + 3ed5ceb3 separation) — verified HIGH
- `frontend/src/components/builder/map-sync.ts` (composition sync, reconciler exports) — verified HIGH
- `frontend/src/components/builder/builder-action-contract.ts` (BuilderLayerAction union) — verified HIGH
- `frontend/src/components/builder/hooks/use-builder-editor-scene.ts` (editor scene controller) — verified HIGH
- `frontend/src/components/builder/hooks/use-builder-layers.ts:1124-1211` (dispatchLayerAction, chatLayerActions) — verified HIGH
- `frontend/src/components/builder/hooks/use-ephemeral-layers.ts` (query result rendering) — verified HIGH
- `frontend/src/components/builder/hooks/use-builder-save.ts:389-510` (save/dirty state) — verified HIGH
- `frontend/src/components/builder/layer-adapters/{fill,line}-adapter.ts` (adapter contract) — verified HIGH
- `frontend/src/components/builder/layer-adapters/shared.ts` (owned-property reconciler, custom paint props) — verified HIGH
- `frontend/src/components/builder/LayerStyleEditor/{LineEditor,RenderModeSwitch}.tsx` (editor lookup table) — verified HIGH
- `frontend/src/components/builder/renderAs.ts` (RenderAsId capability table) — verified HIGH
- `.planning/PROJECT.md` (v1030 scope, v1027/v1026/v1008 substrate) — verified HIGH
- `todo.md:138-152` (live polish backlog) — verified HIGH
- `git show 3ed5ceb3` (in-flight share/access polish) — verified HIGH

**Overall research confidence:** HIGH. All recommendations cite specific files/line numbers from the substrate. No external research needed (per PROJECT.md line 34).
