# Feature Landscape — v1030 Map Builder Polish Sweep

**Domain:** Map builder polish sweep for an on-premises PostGIS GIS catalog. AI chat polish, sharing/embed UX, per-layer-type editor wins, map-level polish, easy-win UX.
**Researched:** 2026-05-27
**Reference tools surveyed:** Felt + Felt AI, Atlas.co (Navi), Mapbox Studio + MapGPT + MCP DevKit, ArcGIS Online Map Viewer (June 2025 update), kepler.gl, QGIS Cloud / QGIS web, Mango, MapTiler raster engine, MapLibre GL JS style spec, OpenLayers, openmaptiles.org, MapBuilder (WRI).

## Scope Disclaimer

PROJECT.md v1030 lists explicit OUT-OF-SCOPE items: annotation/draw layer, LiDAR support, "Text as a layer type", new LLM provider integrations, new connector backends. The findings below respect that scope; defer-flagged items are called out as anti-features for v1030 (most can land in a later milestone).

This research is opinionated. Each finding has explicit complexity (S/M/L), category (table stakes / differentiator / anti-feature), dependency on existing substrate, and a v1030 verdict (ADOPT / DEFER / EVALUATE).

Substrate confirmed by code-read (HIGH confidence):
- `frontend/src/components/builder/ChatPanel.tsx` — streaming chat, AbortController cancel, `inflightRef` lock, single-level undo via `lastSnapshotRef` (Phase 20260526-builder-audit), session-storage 50-msg cap, smart suggestions, retry on transient errors, progressive timeout messages (5s / 15s / 30s)
- `frontend/src/components/builder/SharePanel.tsx` — three-state visibility radio (private/internal/public), share token + embed token separation, allowed-origins comma-input, expiration date, dirty-state warning banner, regenerate-link flow when raw token lost, embed token regeneration affordance, customize params (`zoom`, `center`, `legend`)
- `frontend/src/components/builder/LayerStyleEditor/{Fill,Line,Circle,Symbol,Heatmap,Cluster,Raster}Editor.tsx` — per-render-mode controls already factored, RasterEditor is a placeholder
- `frontend/src/components/builder/LayerEditorPanel.tsx` — tab strip (Style/Filter/Labels/Popup), render-as confirm dialog (destructive switch already gates), scroll/focus preservation across scene transitions
- `frontend/src/components/builder/SettingsEditorScene.tsx` — Appearance / Terrain / Widgets / Projection collapsibles
- `frontend/src/components/builder/MapToolbar.tsx` — Pan/Measure/Legend/StyleJSON pills with V/M/L shortcuts displayed in tooltip
- `frontend/src/components/builder/builder-action-contract.ts` — typed action union with `source: 'manual' | 'ai' | 'system'` (v1027)
- `frontend/src/components/builder/chat-suggestions.ts` — geometry-aware suggestion chips
- `frontend/src/components/builder/DataDrivenStyleEditor.tsx` — quantile + equal_interval classification, color ramps, graduated size

todo.md polish items already cross-referenced (lines 100-170): expand caret too small, opacity slider on sublayers, DETAIL LEVEL toggle removal, draggable basemap, regular layer toggle bug, Map Settings widgets question, "rename group" focus bug, delete layer bug, small-screen overlap collisions (right-sidebar over zoom controls, lat/long pill over widget container, basemap selector double-X), export "powered by GeoLens" + legend + title, popup URL/media handling, AI chat for layer creation / data analysis (line 171).

---

## Category: AI CHAT POLISH (REQ-AI-CHAT-*)

### Table Stakes

| # | Feature | Complexity | Substrate Dependency | v1030 Verdict | Notes |
|---|---------|------------|----------------------|---------------|-------|
| AI-01 | Confirm-before-apply for destructive actions (`add_layer`, `remove_layer`, `clear_paint`+`replace_paint=true`) | M | Existing `ChatAction` type already discriminates these — extend ChatPanel to gate them behind an inline "Apply / Discard" pill when `action.source === 'ai'` | ADOPT | todo.md line 108: "AI - confirm before applying changes to map". Felt/Atlas apply immediately; we differentiate by offering an opt-out toggle in Settings. Existing undo (`lastSnapshotRef`) already covers replay-safe edits, but `add_layer` is flagged `supportsUndo: false` — confirm-before-apply closes that gap. |
| AI-02 | Persistent "Disabled" / "Provider Not Configured" empty state with admin link | S | `useAIStatus` hook exists (referenced in MEMORY for v1010.2 SF-06); ChatPanel mounted conditionally upstream | ADOPT | v1028 closed "actionable AI unavailable state" but only at the mount gate. Re-verify the empty state shows a one-click jump to `/admin/settings/ai`. |
| AI-03 | Error message taxonomy: 401 / 403 / 502 / 503 / network / timeout / abort — each with retry affordance | S | `mapApiErrorToMessage` already taxonomizes; just verify all 4xx/5xx branches resolve to translated strings (no `chat.errorFriendly` fallback for known status codes) | ADOPT | ChatPanel.tsx:199-206 already does this. Verify i18n keys present in all 4 locale files. |
| AI-04 | Streaming feedback with tool-progress label (e.g., "Searching datasets…", "Computing breaks…") | S | `tool_start`/`tool_result` SSE events already wired (ChatPanel.tsx:365-370) | ADOPT — verify | Confirm at least 3 server-side tools emit useful labels. Currently dependent on backend `/ai/chat/` emitting them. |
| AI-05 | Suggestion chips on empty state (geometry-aware) | S | `chat-suggestions.ts` already implements 4-chip geometry-aware suggestion | ADOPT — extend | Add a "Summarize this layer" chip when a layer is selected. Add a "Which datasets cover this view?" chip when bounds are set and >0 datasets exist outside view. |
| AI-06 | Single-level undo for replay-safe actions | S | `lastSnapshotRef` already gates on `isUndoSafeAction` (excludes add/remove/query) | ADOPT — verify | Verify Phase 20260526-04 work surfaces an Undo button on the most recent assistant message. |
| AI-07 | Cancel in-flight request | S | `AbortController` + `inflightRef` lock already in ChatPanel | ADOPT — verify | Verify Square icon button replaces Send during loading; verify mid-stream cancel preserves partial actions. |

### Differentiators

| # | Feature | Complexity | Substrate Dependency | v1030 Verdict | Notes |
|---|---------|------------|----------------------|---------------|-------|
| AI-08 | "Data analysis" mode — chat returns chart/stat result inline as a `show_query_result` action without creating a layer | M | `show_query_result` ChatAction type already exists with `geojson` + `bbox`; needs a non-layer "Inline result card" rendering path | ADOPT | todo.md line 171 explicitly calls out "data analysis". Felt does this via the popup engine + custom JS; we should keep it inline in chat. Server-side already supports the action shape. |
| AI-09 | Action preview cards in assistant message (each action displayed as a small chip — e.g., "Set fill to #ff6b35 on Roads") | S | `msg.actions` already attached to assistant message; current UI shows only count — extend to render per-action chips with revert dot | ADOPT | Felt-style "what changed" view increases user trust before the inline-undo button. Cheap win. |
| AI-10 | Prompt mentions (`@layer`, `@dataset`, `@column`) with mention dropdown | S | `MentionDropdown.tsx` already exists in builder folder; verify it's wired to ChatInput.tsx | ADOPT — verify | Felt and Atlas both use this; mention syntax is referenced in chat-suggestions.ts line 11 (`@[name]` or `@name`). Verify the dropdown actually triggers in ChatInput. |
| AI-11 | Stop-and-revise flow — when user types while assistant is streaming, queue + suggest "Stop current, run new?" | M | Existing inflight lock guards re-entrancy; add a "queued message" buffer | DEFER | Nice-to-have but adds state machine complexity. Out of scope for polish milestone unless it's already half-built. |
| AI-12 | "What can I ask?" tour or starter prompt library | S | Could mount on first chat-open per `mapId` (sessionStorage-based) | EVALUATE | Helps new users; low cost. Felt does this via the empty-state itself with longer descriptive suggestion buttons. |
| AI-13 | Apply-to-many-layers prompts ("color all polygon layers by area") | L | Server-side LLM prompt change + action batching | DEFER | Useful but requires backend prompt + action contract changes. Out of scope. |

### Anti-Features (DO NOT BUILD)

| # | Feature | Why Avoid | Alternative |
|---|---------|-----------|-------------|
| AI-A1 | Inline code/SQL editor (Felt AI Extensions shape) | Out of scope per PROJECT.md ("new LLM provider integrations" + "large new feature builds"); requires sandboxed eval, security review, separate UI tab | Keep chat conversational; offer Style JSON dialog for power users |
| AI-A2 | Multi-turn "approve plan then execute" flow | Adds 2-3 round trips for low-stakes edits; users expect immediate feedback per Felt/Atlas pattern | Per-action confirm gate (AI-01) suffices for destructive actions; otherwise apply-and-undo |
| AI-A3 | LLM provider swap UI in chat (model picker) | Out of scope; provider is admin-configured via env / settings | Keep model selection at admin scope |
| AI-A4 | Chat history pinning, branching, or named conversations | sessionStorage-based ephemeral history (50-msg cap) is the intentional v1027 contract; persistent chat is a separate feature surface | Defer to v1031+ |

---

## Category: SHARING / EMBED POLISH (REQ-SHARE-*)

### Table Stakes

| # | Feature | Complexity | Substrate Dependency | v1030 Verdict | Notes |
|---|---------|------------|----------------------|---------------|-------|
| SHARE-01 | Fresh-token-only-once messaging — when reopening dialog after session reset, show explicit "regenerate to see again" with one click | S | `rawShareToken` state + `handleRegenerateShareLink` already implemented; SharePanel.tsx:622-647 already shows the warning + button | ADOPT — verify | Verify message text is clear ("For security, full link only shown when created"). Verify regenerate sequence does revoke→create + creates embed token if needed. |
| SHARE-02 | Allowed-origins authoring — accept comma-separated input, normalize (strip trailing slash, add `https://` if scheme missing), show parsed values back as chips/list | S | `parseOrigins()` in SharePanel.tsx:24-31 already normalizes; UI only shows comma string | ADOPT — extend | Show parsed origins as chips after Save so user sees what was actually persisted. Common confusion source. |
| SHARE-03 | Iframe embed preview — render the actual iframe inside the dialog at small scale so user sees what they're shipping | M | `generateEmbedCode()` already produces the snippet; add a preview pane that renders it (sandboxed) | ADOPT | Felt and ArcGIS both do this. Reduces "paste-then-check" round trip. Low risk — preview uses same sandboxed iframe attrs as production embed. |
| SHARE-04 | Expiration UX — date picker with "Never" preset, "1 day / 7 days / 30 days / 1 year" quick-presets, plus custom | S | Date input + `handleSaveExpiration` already wired in ShareLinkSettings | ADOPT | Existing input is raw `<Input type="date">`; quick-presets are a 30-min win. |
| SHARE-05 | Status summary line (expires / domains-restricted-to / non-public-layers-warning) | S | Already implemented (SharePanel.tsx:656-666) | ADOPT — verify | Re-verify line is readable and not cropped at narrow widths. |
| SHARE-06 | Save-state warning ("unsaved changes are only in builder preview") | S | Already implemented (SharePanel.tsx:512-541) | ADOPT — verify | Verify warning shows correct copy across `saved` / `unsaved` / `saving` / `failed` states. |

### Differentiators

| # | Feature | Complexity | Substrate Dependency | v1030 Verdict | Notes |
|---|---------|------------|----------------------|---------------|-------|
| SHARE-07 | "Powered by GeoLens" branding on shared/embedded community edition maps + corner watermark on exported PNGs | M | `useEdition()` hook already exists (SharePanel.tsx:11,322); need viewer + ViewerMap + thumbnail-capture paths to read it | ADOPT | todo.md line 151: "export map should show 'powered by geolens' if community"; also broadens to embed surface. Enterprise can suppress via `useEdition().isEnterprise`. Standard open-core watermark pattern (Leaflet attribution-by-default). |
| SHARE-08 | OpenGraph + Twitter card meta for `/m/<token>` URLs — 1200×630 PNG generated server-side from saved thumbnail | M | Existing map thumbnail capture path produces preview PNGs (sessionStorage `geolens-chat-` ≠ thumbnail; check `use-quicklook.ts` + the autocaptured-map registry from v1010.2 SF-07) | EVALUATE | Per research, missing `og:image` cuts CTR 40-60%. For a public-map share workflow this is high-leverage. Requires backend route to serve the OG image at the share-token URL + minimal HTML wrapper. **May be too large for v1030** — flag for v1031 unless thumbnail capture already produces a 1200×630 variant. |
| SHARE-09 | Legend + title in exported map (PNG) | M | Existing widget infra has legend; export path needs to overlay header + footer | ADOPT | todo.md line 151. Felt-style export. Composes with SHARE-07. |
| SHARE-10 | Embed customization params surfaced as a "Configure" panel with toggles (Show legend / Show title / Show coord-readout / Hide attribution) | S | Customize params already documented in dialog (SharePanel.tsx:763-770: `zoom=N`, `center=…`, `legend=…`); needs UI to flip them and append to snippet | ADOPT | Reduces customize friction. User edits chips → snippet regenerates live. |
| SHARE-11 | "Reset all sharing" / "Revoke + regenerate everything" — wipe share token + all embed tokens, force fresh start | S | Existing endpoints (`useRevokeShareToken`, `useRevokeEmbedToken`) | EVALUATE | Useful when domain restrictions drift. Already partially possible via Revoke; consolidate as one action. |
| SHARE-12 | Multi-domain embed tokens (per-domain restriction with separate tokens) | L | Backend supports `allowed_origins` array per token but UI assumes 1 token | DEFER | Edge case. Workaround: customers can use multiple share tokens. Out of scope. |

### Anti-Features

| # | Feature | Why Avoid | Alternative |
|---|---------|-----------|-------------|
| SHARE-A1 | Per-viewer authentication on shared links (email login required) | Out of scope — community has no SMTP; defeats "public" semantics | Stick to token-based authenticated embed for non-public layers |
| SHARE-A2 | Real-time collaborator presence ("X is viewing this map") | Out of scope (per PROJECT.md no map collaboration features); requires WebSocket infra | Defer to a future collaboration milestone |
| SHARE-A3 | Public map directory / search (community gallery) | Out of scope per PROJECT.md (line 30: "public map (separate from embed work)") | Keep individual shares only |
| SHARE-A4 | Password-protected shares | Adds auth flow surface area; allowed-origins + expiration cover most use cases | Use domain restrictions + expiration |

---

## Category: PER-LAYER-TYPE EDITOR POLISH (REQ-EDITOR-*)

Substrate: each render mode has a dedicated editor under `frontend/src/components/builder/LayerStyleEditor/`. RenderModeSwitch dispatches by lookup table. Common controls (Stroke, StyleColor, SliderRow, ZoomExpressionEditor) are factored out. RasterEditor is currently a stub. Findings target gaps relative to ArcGIS Map Viewer (June 2025), kepler.gl, and MapLibre style spec.

### Fill / Polygon

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-FILL-01 | `fill-pattern` (raster/SVG image fill via sprite) | M | Differentiator | DEFER | Mapbox/MapLibre support; needs sprite upload flow → too big for polish. |
| EDITOR-FILL-02 | `fill-translate` + `fill-translate-anchor` (offset polygon paint) | S | Table stakes | EVALUATE | Already in Mapbox studio; low usage on flat data. Add slider row if cheap. |
| EDITOR-FILL-03 | Gradient fill (June 2025 ArcGIS) | L | Differentiator | DEFER | MapLibre doesn't natively support `fill-gradient` paint property. Skip. |
| EDITOR-FILL-04 | Heights-by-expression preview (when `_height_column` set, show feature samples + range) | S | Easy-win | ADOPT | FillEditor.tsx:62-91 already includes the height column dropdown with broken-column warning. Add a one-line preview ("Range: 5–142 m, 1,204 features") under the dropdown using `dataset_sample_values`. |
| EDITOR-FILL-05 | "Outline only" preset shortcut (set fill-opacity=0, stroke on) | S | Easy-win | ADOPT | Common cartographic choice; one-click preset above Stroke switch. |

### Line

Reference tools: Mapbox Style Spec, ArcGIS SimpleLineSymbol, TileMill. Industry-standard line controls include cap/join/miter, dash patterns, gradient, gap-width, blur, offset.

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-LINE-01 | `line-cap` (butt / round / square) | S | Table stakes | ADOPT | Currently absent from LineEditor.tsx. Standard control across every reference tool. Quick segmented control. |
| EDITOR-LINE-02 | `line-join` (bevel / round / miter) + `line-miter-limit` | S | Table stakes | ADOPT | Currently absent. Standard control. |
| EDITOR-LINE-03 | Dash pattern presets | S | Table stakes | ADOPT — verify | LineEditor.tsx already implements LINE_DASH_PRESETS preset row. Verify presets render. |
| EDITOR-LINE-04 | Line gradient (`line-gradient` paint with `line-progress` interpolation) | S | Differentiator | ADOPT — verify | LineGradientControls.tsx exists; verify the gradient editor surfaces in builder. |
| EDITOR-LINE-05 | Arrow companion layer | S | Differentiator | ADOPT — verify | Already shipped (v1027 / MEMORY references it). Verify Arrow controls (size, spacing, color) work in current build. |
| EDITOR-LINE-06 | `line-sort-key` for z-ordering | S | Anti-feature for v1030 | DEFER | Power-user feature; expose via Style JSON if needed. |

### Circle / Point

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-CIRCLE-01 | `circle-translate` slider | S | Easy-win | EVALUATE | Mostly unused; skip unless trivially scoped. |
| EDITOR-CIRCLE-02 | `circle-pitch-alignment` / `circle-pitch-scale` for 3D maps | S | Differentiator | DEFER | Needed only when 3D/globe is used; defer. |
| EDITOR-CIRCLE-03 | "Quick preset" row (Default / Small / Large / Outlined) | S | Easy-win | ADOPT | Felt-style "smart symbology" entry point. Reduces 3-slider-tweaking-from-scratch fatigue. |

### Symbol (Icon)

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-SYMBOL-01 | Icon search/filter in IconPicker | S | Easy-win | EVALUATE | If IconPicker has 30+ icons, search becomes table stakes. Check current icon library size. |
| EDITOR-SYMBOL-02 | Icon upload (per-map sprite) | L | Differentiator | DEFER | Backend sprite endpoint needed; out of scope. |
| EDITOR-SYMBOL-03 | `icon-allow-overlap` toggle | S | Table stakes | ADOPT | Cluster + dense point layers hide labels by default. Toggle is standard. |
| EDITOR-SYMBOL-04 | Categorical icon mapping (already partial in SymbolEditor.tsx:89-124) — improve to use real distinct-value query instead of `dataset_sample_values` truncation | S | Easy-win | EVALUATE | Current shows only 6 sample values; for low-cardinality columns this misses categories. If a `useColumnDistinctValues` hook exists, swap; else defer. |

### Heatmap

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-HEAT-01 | `heatmap-radius` / `heatmap-intensity` / `heatmap-weight` / `heatmap-opacity` zoom-expression controls | S | Table stakes | ADOPT — verify | HeatmapStyleControls.tsx already exists; verify all 4 properties exposed with ZoomExpressionEditor. |
| EDITOR-HEAT-02 | Color ramp presets aligned with cartographic palettes (sequential / diverging) | S | Easy-win | EVALUATE | ColorRampPicker likely already presets these; verify. |

### Cluster

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-CLUSTER-01 | Cluster threshold (`clusterMaxZoom`) | S | Table stakes | ADOPT — verify | ClusterEditor.tsx:27-34 already exposes this. |
| EDITOR-CLUSTER-02 | Cluster count text formatter ("1.2k" instead of "1234") | S | Easy-win | ADOPT | Common cartographic touch; one helper function applied to text-field expression. |
| EDITOR-CLUSTER-03 | Cluster size by count (radius interpolation) | S | Differentiator | EVALUATE | Already partially in `clusterRadius` — verify it interpolates or is fixed. If fixed, expose a "scale with count" toggle. |

### Raster

`RasterEditor.tsx` is currently a stub. MapLibre raster paint supports: `raster-opacity`, `raster-hue-rotate` (0-1), `raster-brightness-min`/`max` (0-1), `raster-saturation` (-1 to 1), `raster-contrast` (-1 to 1), `raster-fade-duration`, `raster-resampling` (linear/nearest).

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-RASTER-01 | Brightness / Contrast / Saturation / Hue-Rotate sliders | S | Table stakes | ADOPT | RasterEditor.tsx is literally a placeholder (file confirms "TODO(1047-05)"). 4 sliders = 30-min win. QGIS, ArcGIS, AutoCAD, GeoServer all expose these. |
| EDITOR-RASTER-02 | `raster-resampling` toggle (linear vs nearest) | S | Easy-win | ADOPT | One segmented control; useful for categorical rasters (nearest preserves classes). |
| EDITOR-RASTER-03 | Stretch / colormap controls for single-band rasters | L | Differentiator | DEFER | Titiler supports server-side; UI to author per-band stretch is a separate milestone. |
| EDITOR-RASTER-04 | Reset-to-default button | S | Easy-win | ADOPT | After 4 sliders are added, a single Reset button is table-stakes. |

### Basemap (BasemapGroupRow + Sublayer Scenes)

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-BASEMAP-01 | Draggable basemap row in stack | M | Table stakes | ADOPT — verify | todo.md line 142 + v1011 BUG-03 "basemap should be draggable in layer order" — MEMORY says v1011 closed via `MapBasemapConfig.basemap_position` jsonb-additive. Verify in live builder. |
| EDITOR-BASEMAP-02 | "Make basemap optional" / "No basemap" preset | S | Easy-win | ADOPT | todo.md line 99. One additional preset in the basemap picker. Implementation = empty style. |
| EDITOR-BASEMAP-03 | Remove DETAIL LEVEL toggle (dead-wired) | S | Easy-win | ADOPT | todo.md line 141. MEMORY confirms v1011 INV-01 documented disposition (REMOVE chosen over FIX). Verify removal landed; if not, complete in v1030. |
| EDITOR-BASEMAP-04 | Sublayer expand caret enlarged | S | Easy-win | ADOPT | todo.md line 139 "expand carrot for layer groups is too small". |
| EDITOR-BASEMAP-05 | Sublayer config indicators (label / filter / etc) instead of redundant opacity slider | S | Easy-win | ADOPT — verify | todo.md line 140. MEMORY says v1011 UX-02 closed via `SublayerConfigIndicators` pure-derivation badges. Verify the live build. |
| EDITOR-BASEMAP-06 | Custom style URL override | M | Differentiator | DEFER | Per existing research question (questions.md line 33): how does custom basemap decompose? Out of scope for polish. |

### DEM / Terrain

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EDITOR-DEM-01 | Render-as switch (Image / Hillshade / Terrain) | S | Table stakes | ADOPT — verify | v1008 shipped DEM-as-raster-layer with image/hillshade/terrain modes. Verify the switch + paint defaults survive a save/reload. |
| EDITOR-DEM-02 | Terrain exaggeration slider (`bind_dem_terrain` + `set_dem_terrain_exaggeration`) | S | Table stakes | ADOPT — verify | Already in builder-action-contract. Verify the slider lives in DEMEditorScene or RasterLayerControls. |
| EDITOR-DEM-03 | Hillshade light direction + altitude controls | S | Differentiator | EVALUATE | MapTiler / ArcGIS June-2025 expose this. Composes well with hillshade render-mode. If MapLibre `hillshade-illumination-direction` / `hillshade-illumination-anchor` are not already in TerrainControls.tsx, this is a cheap add. |
| EDITOR-DEM-04 | Contour lines as derived layer | L | Differentiator | DEFER | Requires server-side contour generation (gdal_contour). Out of scope. |
| EDITOR-DEM-05 | Hypsometric tint (color-by-elevation) | M | Differentiator | DEFER | Felt 2025 raster engine ships this; we don't have the dynamic colormap UI. Defer. |

---

## Category: MAP-LEVEL POLISH (REQ-MAP-*)

### Viewport & State

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| MAP-01 | Save viewport (center + zoom + bearing + pitch) on every save | S | Table stakes | ADOPT — verify | Server schema already supports a `viewport` shape (per existing code patterns). Verify save round-trips it without resetting on viewer-open. |
| MAP-02 | Restore viewport on viewer/embed open (vs. fit-to-bounds default) | S | Table stakes | ADOPT — verify | Standard UX. Verify ViewerMap honors saved viewport when present. |
| MAP-03 | "Fit to data" button on toolbar | S | Easy-win | ADOPT | Quick way back to data extent. Already common in Felt/ArcGIS. Implementation = `fitBounds` to union of layer source bounds. |
| MAP-04 | Dirty-state indicator in title bar | S | Table stakes | ADOPT — verify | todo.md line 105 marked DONE in v13.11 QUALITY-01. Re-verify the orange dot is still visible after recent refactors. |
| MAP-05 | Auto-save on idle (vs. explicit Save button) | M | Anti-feature | DEFER | Adds race conditions with AI chat unsaved-actions semantics. Keep explicit Save. Existing v1027 contract assumes manual save. |
| MAP-06 | Title editing inline (vs. settings panel) | S | Easy-win | ADOPT — verify | `MapTitleBar.tsx` exists. Verify the title is double-click-editable. |

### Smaller-screen Layout (todo.md lines 147-149)

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| MAP-07 | Right sidebar must not overlap zoom controls when collapsed | S | Bug | ADOPT | todo.md line 147. Already partially fixed in v1011 (NavigationControl moved to `top-left` per `[data-builder-canvas="true"]`). Verify across the breakpoints (≤800px, 800-1200px, ≥1200px). |
| MAP-08 | Lat/long pill must not overlay widget container | S | Bug | ADOPT | todo.md line 148. MapCoordReadout positioning fix (v1011 RESP-02). Verify on small viewports. |
| MAP-09 | Basemap selector single-X (no double close-button) | S | Bug | ADOPT | todo.md line 149. v1011 RESP-03 closed via `<SheetContent showCloseButton={false}>`. Re-verify. |
| MAP-10 | Single-X across all right-sidebar Sheets | S | Bug | ADOPT | todo.md line 149 (extension). Audit all Sheet/Dialog usages in builder for `showCloseButton` consistency. |
| MAP-11 | Layer-stack panel collapsing to bottom drawer on ≤640px | L | Differentiator | DEFER | Major mobile UI work; out of scope. The current `<800px` Sheet drilldown was v1008. |
| MAP-12 | Touch-target audit (44px minimum) on map controls | S | Easy-win | EVALUATE | Existing PROJECT.md mentions "44px mobile touch targets". Spot-check toolbar buttons during the walkthrough. |

### Settings / Widgets

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| MAP-13 | Settings Widgets section: clarify "Controls whether each widget appears on the map" | S | Easy-win | ADOPT — verify | SettingsEditorScene.tsx:180-184 already adds this clarifier. Verify text reads cleanly. todo.md line 144 was the original question. |
| MAP-14 | Background color reset | S | Easy-win | ADOPT — verify | SettingsEditorScene.tsx:95-106 has RotateCcw reset. Verify it actually resets to `null` and the basemap shows. |
| MAP-15 | Projection switch (Mercator / Globe) | S | Differentiator | ADOPT — verify | Already in SettingsEditorScene.tsx:215-277. v1027/v1028 should have this; verify Globe disclaimer alert appears. |
| MAP-16 | Rename group focus bug fix | S | Bug | ADOPT | todo.md line 145. Trivial fix — `inputRef.current?.focus()` + `select()` in the rename modal's useEffect. |
| MAP-17 | Delete layer fix | S | Bug | ADOPT | todo.md line 146. Higher priority — direct user-reported regression. Investigate StackRow `···` menu Delete handler. |
| MAP-18 | Regular layer toggle (visibility) fix | S | Bug | ADOPT | todo.md line 143 — explicit broken map URL referenced. Inspect `onToggleVisibility` handler chain through `dispatchBuilderLayerAction → setVisibility`. |

### Map Functionality

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| MAP-19 | Map scroll prevention when interacting with layer panel | S | Bug | ADOPT | todo.md line 136 "map is scrollable". Likely a CSS overscroll-behavior fix or pointer event guard on the sidebar overlay. |
| MAP-20 | Filter pills not colliding with measure widget | S | Bug | ADOPT | todo.md line 103. Position `ActiveFilterChips` to avoid widget container space. |
| MAP-21 | "Pending style preview" banner accuracy (gates on deep-equal diff vs. saved baseline) | S | Easy-win | ADOPT — verify | MEMORY: v1009.1 SP-05 closed via deep-equal dirty gate. Verify the banner doesn't fire on save round-trips. |
| MAP-22 | Notes panel — indicator if notes exist | S | Easy-win | ADOPT | todo.md line 101 "indicator on notes icon if there are any". Small dot/badge on the rail's Notes button. |

---

## Category: EASY-WIN UX (REQ-EASY-*)

### Discoverability & Affordances

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EASY-01 | Keyboard shortcut overlay ("?" key shows shortcut cheat sheet) | S | Differentiator | EVALUATE | MapToolbar.tsx already shows V/M/L shortcuts in tooltips. A "?" overlay is the standard discoverability. Implementation = simple modal. Felt + Atlas both do this. |
| EASY-02 | Cmd/Ctrl+S = Save | S | Table stakes | ADOPT | Universal. One keyboard listener gated on map-builder route. |
| EASY-03 | Cmd/Ctrl+Z / Cmd+Shift+Z for builder history undo/redo | S | Table stakes | EVALUATE | History panel exists. Wire keyboard shortcuts to dispatch the same actions. Verify it doesn't conflict with browser default. |
| EASY-04 | Esc = close active editor / Sheet / Dialog | S | Table stakes | ADOPT — verify | Radix Dialog/Sheet handle this by default. Audit any non-Radix overlays. |
| EASY-05 | Hover affordance on layer rows (raised state) | S | Easy-win | ADOPT — verify | MEMORY: v1009.1 SP-14 closed. Re-verify on live build. |
| EASY-06 | Layer row context (right-click) menu mirroring `···` menu | S | Differentiator | EVALUATE | Standard pro-tool affordance. Reuse the `···` menu's items. |
| EASY-07 | Layer thumbnails in stack (mini preview of the layer's geometry/color) | M | Differentiator | DEFER | Felt and Atlas do this. Requires per-layer thumbnail render. Cost > benefit for v1030 polish; defer. |
| EASY-08 | Bulk-action shortcuts (Shift-click range-select already shipped per v1009.1 SP-04) | S | Easy-win | ADOPT — verify | Re-verify shift-click range still works after recent refactors. |
| EASY-09 | Layer icon shows current color (already shipped per ColorizedGeometryIcon) | S | Easy-win | ADOPT — verify | LayerEditorPanel.tsx:159-169 uses `ColorizedGeometryIcon` + `extractStyleHints`. Verify the swatch updates live as user edits color. |
| EASY-10 | Coord readout shows scale "1:N" (representative fraction) | S | Differentiator | ADOPT — verify | MEMORY: v1009.1 SP-12 closed via `showScale` prop + formatter helper. Re-verify on live build. |

### Workflow

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EASY-11 | Popup URL/link/media handling | S | Easy-win | ADOPT | todo.md line 96 "links/media to popups?" + line 163 "popup should handle URLs and media". Per QGIS/MapBuilder/ArcGIS pattern: detect URLs ending in `.jpg`/`.png`/`.mp4`/`.youtube.com/...` and render as image/video/link. Implementation in PopupConfigEditor + the popup-renderer at view time. Document the `{column}` token substitution syntax. |
| EASY-12 | Notes panel autosave + revert | S | Easy-win | EVALUATE | If notes already autosave (MEMORY notes "Notes clear/persistence fixes" in v1028), verify. |
| EASY-13 | Duplicate layer in `···` menu | S | Easy-win | ADOPT — verify | `duplicateRendering` action already in builder-action-contract. Verify menu item exists in StackRow. |
| EASY-14 | "Add Data" empty state has 3-4 curated dataset suggestions | S | Easy-win | ADOPT — verify | v1008 shipped this. Verify suggestion list works against current catalog. |
| EASY-15 | Filter pills show count, click to clear | S | Easy-win | ADOPT — verify | `ActiveFilterChips.tsx` exists. Verify click-to-clear works. |
| EASY-16 | Layer count in title bar ("3 layers · 1 hidden") | S | Easy-win | EVALUATE | Felt-style status line. Quick add to MapTitleBar. |
| EASY-17 | "Saved X minutes ago" timestamp in title bar | S | Easy-win | EVALUATE | Composes with MAP-04 dirty indicator. Cheap. |

### Edge Cases

| # | Feature | Complexity | Category | v1030 Verdict | Notes |
|---|---------|------------|----------|---------------|-------|
| EASY-18 | Empty layer state (0 features) — show "Layer is empty, check your filter or source" | S | Easy-win | ADOPT | Common confusion when filter eliminates all features. Check at render time and show inline message in layer editor. |
| EASY-19 | Failed tile error overlay with retry | S | Easy-win | ADOPT — verify | MapLibre emits `error` events; Existing builder likely handles. Verify retry surface. |
| EASY-20 | Rename validation — disallow empty + duplicate names | S | Easy-win | ADOPT — verify | Standard. Verify the rename modal validates. |

---

## Feature Dependencies (Within v1030 Polish Scope)

```
SHARE-02 (origins as chips)        → depends on SHARE-01 (regenerate flow)
SHARE-09 (legend+title in export)  → depends on SHARE-07 (powered-by branding)
SHARE-08 (OG cards)                → depends on existing thumbnail capture path (verify before scoping)
SHARE-10 (customize panel)         → depends on viewer accepting query params (already does per SharePanel.tsx:763-770)

AI-01 (confirm-before-apply)       → depends on builder-action-contract source discriminator (v1027) — ALREADY SATISFIED
AI-08 (data analysis card)         → depends on existing show_query_result action shape — ALREADY SATISFIED
AI-09 (action chips)               → depends on AI-01 + msg.actions render path

EDITOR-RASTER-01..04               → depend on MapLibre raster paint properties — ALREADY SATISFIED (style spec)
EDITOR-LINE-01,02                  → depend on layout properties (not paint); ensure handlers cover layout

MAP-07,08,09,10                    → depend on continued v1011 fixes; mostly re-verifications
MAP-04                             → depends on existing dirty-state plumbing — ALREADY SATISFIED (v13.11)

EASY-02,03,04                      → depend on a single keyboard-shortcut listener mounted at MapBuilderPage level
EASY-11                            → depends on PopupConfigEditor changes + viewer-time popup-renderer changes
```

No external substrate dependencies (LLM provider, new backend services, schema migrations) are required for the ADOPT-tagged items.

---

## MVP Recommendation for v1030

Given the milestone is polish (not new architecture), prioritize like this:

### Tier 1 — Bugs from todo.md (must fix)
1. **MAP-17 Delete layer fix** (todo.md line 146) — explicit broken-on-live-map regression.
2. **MAP-18 Regular layer toggle fix** (todo.md line 143) — broken-on-live-map regression.
3. **MAP-16 Rename group focus** (todo.md line 145) — trivial focus management.
4. **MAP-07/08/09/10 Small-screen layout collisions** (todo.md lines 147-149) — already partially fixed; verify and complete.
5. **MAP-19 Map scroll** (todo.md line 136).
6. **MAP-20 Filter pills vs. measure widget** (todo.md line 103).

### Tier 2 — Per-render-mode editor table stakes
7. **EDITOR-RASTER-01..04** Brightness/Contrast/Saturation/Hue + reset — currently a stub, biggest single-file win.
8. **EDITOR-LINE-01/02** line-cap, line-join — universal cartographic controls absent.
9. **EDITOR-FILL-04** Height column range hint — composes with existing 3D extrusion.
10. **EDITOR-BASEMAP-03** Remove DETAIL LEVEL toggle.
11. **EDITOR-BASEMAP-02** "No basemap" preset.

### Tier 3 — AI chat polish (todo.md line 171)
12. **AI-01 Confirm-before-apply** for destructive actions — todo.md line 108 explicit.
13. **AI-08 Data analysis card** — surfaces the `show_query_result` action as a inline result card.
14. **AI-09 Action preview chips** — Felt-style "what changed".
15. **AI-05 Selected-layer-aware suggestion chips** — extension of `chat-suggestions.ts`.

### Tier 4 — Share polish
16. **SHARE-02 Origins as chips** (saved-state visibility).
17. **SHARE-04 Expiration presets**.
18. **SHARE-07 "Powered by GeoLens"** branding (todo.md line 151) + **SHARE-09 Legend + title in export**.
19. **SHARE-03 Iframe preview** — if iframe sandbox+sanitization is straightforward; otherwise defer.

### Tier 5 — Easy-win UX
20. **EASY-02 Cmd/Ctrl+S** = Save.
21. **EASY-11 Popup URL/media** (todo.md lines 96 + 163).
22. **EASY-18 Empty-layer state**.
23. **EASY-22 Notes indicator** (todo.md line 101).

### Defer (out of scope or too large for polish milestone)
- SHARE-08 OG cards (depends on capture pipeline scoping)
- EASY-07 Layer thumbnails
- EDITOR-RASTER-03 Stretch/colormap UI
- EDITOR-FILL-01 fill-pattern
- EDITOR-DEM-04/05 contours + hypsometric tint
- All anti-features (AI-A1..A4, SHARE-A1..A4)

---

## Sources

### Reference Tools (Competitor / Best-in-class Surveys)

- [AI in GIS and Location Intelligence for Faster Analysis — Felt](https://felt.com/platform/felt-ai)
- [All-in-One App Builder for Maps and Location Data — Felt](https://felt.com/platform/app-development)
- [Felt AI unleashed: Build spatial applications with just a prompt](https://felt.com/blog/felt-ai-build-spatial-applications-with-just-a-prompt)
- [Felt MCP Server](https://help.felt.com/felt-ai/mcp)
- [Felt Embed Tokens — Developer Docs](https://developers.felt.com/rest-api/api-reference/embed-tokens)
- [Felt Embedding](https://help.felt.com/sharing-and-collaboration/embedding)
- [Felt AI Popups](https://help.felt.com/felt-ai/ai-popups)
- [Felt Dynamic styling, hillshades, & raster algebra](https://felt.com/blog/dynamic-styling-hillshades-and-raster-algebra)
- [Atlas.co — AI Map Generator](https://atlas.co/blog/ai-map-generator-create-maps-with-artificial-intelligence/)
- [Atlas.co — Introducing Navi: AI That Builds Maps From Conversation](https://atlas.co/blog/introducing-navi-ai-that-builds-maps-from-conversation/)
- [Atlas.co — Best AI Tools for GIS Mapping](https://atlas.co/blog/best-ai-tools-for-gis-mapping/)
- [Mapbox MCP DevKit](https://www.mapbox.com/blog/the-mapbox-mcp-devkit-equip-ai-coding-tools-with-geospatial-skills-for-mapbox-development)
- [Mapbox MapGPT](https://www.mapbox.com/mapgpt)
- [Mapbox Agent Skills](https://docs.mapbox.com/api/guides/mapbox-agent-skills/)
- [Mapbox Spring Release 2025](https://www.mapbox.com/blog/mapbox-spring-release-2025-new-features-and-updates)
- [Mapbox Symbol Layer](https://docs.mapbox.com/help/glossary/symbol-layer/)
- [ArcGIS Online — Apply styles](https://doc.arcgis.com/en/arcgis-online/create-maps/apply-styles-mv.htm)
- [ArcGIS Online — Use style options](https://doc.arcgis.com/en/arcgis-online/create-maps/use-style-options-mv.htm)
- [What's new in Map Viewer (June 2025)](https://www.esri.com/arcgis-blog/products/arcgis-online/mapping/whats-new-in-map-viewer-june-2025)
- [ArcGIS Online — Configure pop-ups](https://doc.arcgis.com/en/arcgis-online/create-maps/configure-pop-ups-mv.htm)
- [ArcGIS Online — Use attributes as URL parameters in pop-up links](https://www.esri.com/arcgis-blog/products/arcgis-online/mapping/url-parameters-pop-ups)
- [ArcGIS — Classification methods](https://doc.arcgis.com/en/teams/latest/workflows/classification-methods.htm)
- [ArcGIS — Style imagery in Map Viewer](https://doc.arcgis.com/en/arcgis-online/create-maps/style-imagery-mv.htm)
- [Smart mapping styles in the new Map Viewer — Learn ArcGIS](https://learn.arcgis.com/en/paths/smart-mapping-styles-in-the-new-map-viewer/)
- [kepler.gl Layers documentation](https://docs.kepler.gl/docs/user-guides/c-types-of-layers)
- [kepler.gl Trip layer](https://docs.kepler.gl/docs/user-guides/c-types-of-layers/k-trip)
- [kepler.gl Polygon layer](https://docs.kepler.gl/docs/user-guides/c-types-of-layers/e-polygon)
- [kepler.gl Hexbin layer](https://docs.kepler.gl/docs/user-guides/c-types-of-layers/h-hexbin)
- [QGIS 3.44 Raster Properties Dialog](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_raster/raster_properties.html)
- [QGIS Cloud documentation](https://docs.qgiscloud.com/en/)
- [MapTiler — Hillshade and contour styling](https://www.maptiler.com/terrain/)
- [MapTiler — Style terrain with hillshading](https://docs.maptiler.com/guides/map-design/terrain/hillshading/)
- [MapBuilder (WRI) — Configure pop-ups](https://mapbuilder.wri.org/tutorials/configure-pop-ups/)

### MapLibre / Style-spec Authority

- [MapLibre Style Spec — Layers](https://maplibre.org/maplibre-style-spec/layers/)
- [MapLibre raster paint properties](https://maplibre.org/maplibre-style-spec/layers/)

### Industry / UX Patterns

- [Map UI Patterns — Basemap toggle](https://mapuipatterns.com/basemap-toggle/)
- [Map UI Patterns — Mobile map](https://mapuipatterns.com/mobile-map/)
- [Map UI Patterns — List and details (viewport restoration)](https://mapuipatterns.com/list-details/)
- [Open Graph Image Sizes for Social Media — 2025 Guide](https://www.krumzi.com/blog/open-graph-image-sizes-for-social-media-the-complete-2025-guide)
- [Responsive UI Design Techniques for Web Maps](https://www.maplibrary.org/1216/responsive-design-techniques-for-web-maps/)
- [7 Ideas for Designing Mobile-Friendly Maps](https://www.maplibrary.org/9954/7-ideas-for-designing-mobile-friendly-maps-with-data/)
- [TileMill — Styling Lines (line-cap / line-join reference)](https://tilemill-project.github.io/tilemill/docs/guides/styling-lines/)
- [ArcGIS SimpleLineSymbol — line cap / join / miter](https://developers.arcgis.com/javascript/latest/references/core/symbols/SimpleLineSymbol/)

### Open-source Map Stack Context

- [Leaflet — open-source map library](https://leafletjs.com/)
- [OpenMapTiles](https://openmaptiles.org/)
- [Protomaps](https://protomaps.com/)
- [uMap — Online map creator](https://umap.openstreetmap.fr/en/)

### Internal Substrate (HIGH confidence — code read)

- `frontend/src/components/builder/ChatPanel.tsx` — current AI chat implementation
- `frontend/src/components/builder/SharePanel.tsx` — current share dialog
- `frontend/src/components/builder/LayerStyleEditor/*.tsx` — per-render-mode editors
- `frontend/src/components/builder/LayerEditorPanel.tsx` — tab strip + scene controller
- `frontend/src/components/builder/SettingsEditorScene.tsx` — settings panel
- `frontend/src/components/builder/MapToolbar.tsx` — map toolbar (Pan/Measure/Legend/StyleJSON)
- `frontend/src/components/builder/chat-suggestions.ts` — geometry-aware suggestion chips
- `frontend/src/components/builder/builder-action-contract.ts` — typed action union (v1027)
- `frontend/src/components/builder/DataDrivenStyleEditor.tsx` — classification + color ramps
- `frontend/src/components/builder/LabelEditor.tsx` — label config
- `.planning/PROJECT.md` — milestone scope + recent shipped milestone summaries
- `todo.md` — polish backlog (lines 100-170 + line 171)
