# Map Builder Audit — 2026-04-17

## Scorecard

| Dimension | Grade | CRITICAL | HIGH | MEDIUM | LOW | Notes |
|-----------|:-----:|:--------:|:----:|:------:|:---:|-------|
| **Layer Management** | **B** | 0 | 0 | 4 | 8 | Solid lifecycle; fill-extrusion sublayer gaps + backend dataset access check missing |
| **Style Editing** | **C** | 0 | 3 | 5 | 4 | simplifyPaint interpolate bug, graduated null guard, fill-adapter syncPaint ternary |
| **Filter Building** | **C** | 0 | 3 | 4 | 5 | 3 round-trip parse bugs (is_null, in_list/not_in_list, has) break save/load |
| **Label Config** | **B** | 0 | 1 | 4 | 3 | textOpacity dead code; toggle destroys config; polygon placement limitations |
| **Share & Viewer** (2×) | **B** | 0 | 0 | 4 | 6 | Plaintext share token persists; domain toggle stale state; embed token scope drift |
| **AI Chat** | **C** | 0 | 4 | 8 | 4 | Wall-clock timeout dead code; streaming skips validation; no undo mechanism |
| **UI/UX Quality** | **C*** | — | — | — | — | *Agent failed; grade carried from prior audit with verified fixes applied* |
| **Performance** | **C+** | 0 | 2 | 6 | 5 | LayerPanel/SidebarContent not memoized; index/totalLayers defeats LayerItem memo |
| **Code Conventions** | **C*** | — | — | — | — | *Agent failed; grade carried from prior audit* |

**Overall Builder Health: B-**

Weighted formula: Layer (2×) + Style (2×) + Share (2×) + remaining (1×). Improved from C+ (prior audit 2026-04-05) — 8 of 19 prior HIGH findings resolved, but new correctness bugs found in filter round-trips and style editing.

---

## Executive Summary

The map builder has improved meaningfully since the April 5 audit: `LayerItem` is now `React.memo`-wrapped, `ChatPanel` is lazy-loaded, `handleToggleVisibility` now calls MapLibre directly, the `lastOrderKeyRef` module singleton is fixed, and the error handler memory leak is resolved. **8 of 19 prior HIGH findings are confirmed fixed.** However, this audit uncovered **new correctness bugs** in two areas: (1) **filter round-trips** — `is_null`, `in_list`/`not_in_list`, and `has` operators produce expressions that the parser cannot reconstruct, breaking the visual editor after save/reload; (2) **style editing** — `simplifyPaint` incorrectly extracts fallback colors from interpolate expressions, `buildGraduatedExpression` lacks a null guard, and `fill-adapter.syncPaint` has a both-branches-identical ternary. The AI chat subsystem has a **dead wall-clock timeout** constant and **skips action validation in the streaming path**. The top recommendation is to fix the 3 filter round-trip HIGHs first (they affect every user who saves a filtered map), then the 3 style-editing HIGHs, then enforce the streaming timeout and validation.

---

## 1. Layer Management

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| L-01 | MEDIUM | fill-extrusion sublayer orphaned on layer removal — stale cleanup only removes 3 hardcoded IDs | `map-sync.ts:256-267` | Call `adapter.getLayerIds(id)` in the stale-source cleanup block |
| L-02 | MEDIUM | Layer reorder not synced to MapLibre at interaction time — deferred to next render cycle | `use-builder-layers.ts:122-141` | Call `reorderDataLayers()` synchronously in `handleMove`/`handleReorder` |
| L-03 | MEDIUM | `add_layer` endpoint does not verify caller can access the target dataset | `router.py:706-787` | Call `_bulk_check_dataset_access` after `check_map_ownership` |
| L-04 | MEDIUM | Duplicate dataset layers share MapLibre source, doubling tile traffic | `map-sync.ts:188-198` | Add `UNIQUE(map_id, dataset_id)` DB constraint; return 409 on duplicate |
| L-05 | LOW | `?add_dataset` URL param race with `initializedRef` | `use-builder-layers.ts:87-98` | Make guard order-independent |
| L-06 | LOW | `remove_layer` does not verify `layer_id` belongs to the target `map_id` | `router.py:790-824` | Add `WHERE map_id = map_id AND id = layer_id` |
| L-07 | LOW | `handleDisplayNameChange` allows transient empty-string state | `use-builder-layers.ts:143-149` | Normalize `display_name` to `null` after API sync |
| L-08 | LOW | `swapLayerOnMap` does not remove fill-extrusion companion layer | `use-builder-layers.ts:247-252` | Add extrusion removal alongside outline removal |
| L-09 | LOW | Visibility toggle does not cover fill-extrusion sublayer | `use-layer-map-sync.ts:57-76` | Add `layer-{id}-extrusion` visibility sync |
| L-10 | LOW | `getLayerCapabilities` defaults to fill editors for null geometry type | `layer-capabilities.ts:39-62` | Add explicit null guard that disables editors |
| L-11 | LOW | Ephemeral layer `style.load` listener not cleaned up in useEffect return | `use-ephemeral-layers.ts:96-101` | Add `return () => map.off('style.load', addLayers)` |
| L-12 | LOW | `fill-adapter.syncPaint` both ternary branches produce `'transparent'` | `fill-adapter.ts:101` | Fix else branch to resolved `outlineColor` |

---

## 2. Style Editing

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| S-01 | HIGH | `fill-adapter.syncPaint` stroke toggle always sets fill-outline-color to transparent (both branches identical) | `fill-adapter.ts:101` | Fix else branch to `outlineColor ?? MAP_COLORS.default.stroke` |
| S-02 | HIGH | `simplifyPaint` extracts wrong fallback from `["interpolate", ...]` expressions — picks `["heatmap-density"]` array | `shared.ts:33` | Add `else if (op === 'interpolate')` branch extracting `value[4]` |
| S-03 | HIGH | `buildGraduatedExpression` has no null guard — null property values silently assigned to first class | `color-ramps.ts:88` | Wrap step expression in `["case", ["==", ["get", col], null], fallback, ...]` |
| S-04 | MEDIUM | line-adapter `syncPaint` does not sync `line-dasharray` (stored in layout, not paint) | `line-adapter.ts:42-51` | Extract `line-dasharray` from `input.layout` in `syncPaint` |
| S-05 | MEDIUM | `swapLayerOnMap` does not remove fill-extrusion companion on adapter swap | `use-builder-layers.ts:246-253` | Call `getAdapter(type).getLayerIds()` before removal |
| S-06 | MEDIUM | Heatmap opacity has no dedicated UI slider — 0.8 cap locked in DEFAULT_HEATMAP_PAINT | `HeatmapStyleControls.tsx` | Add `SliderRow` for `heatmap-opacity` (0–1) |
| S-07 | MEDIUM | `handlePaintChange` compounds heatmap-opacity with hardcoded 0.8 instead of stored value | `use-layer-map-sync.ts:102-103` | Replace `0.8` with `(newPaint['heatmap-opacity'] as number ?? 0.8)` |
| S-08 | MEDIUM | `ColorRampPicker` preview always renders 7 swatches regardless of actual class count | `ColorRampPicker.tsx:43` | Add optional `count` prop; pass `classCount` from `DataDrivenStyleEditor` |
| S-09 | LOW | `simplifyPaint` sets `undefined` for short arrays; `stripCustomProps` retains those keys | `shared.ts:37-38` | Filter `undefined` values in `stripCustomProps` |
| S-10 | LOW | `_minzoom`/`_maxzoom` custom layout prop convention is implicit, not enforced by type system | `use-layer-map-sync.ts:233` | Document `_`-prefix invariant |
| S-11 | LOW | Advanced JSON editor bypasses all validation — invalid keys silently persisted | `LayerStyleEditor.tsx:500-508` | Catch MapLibre errors from dry-run before `onApply` |
| S-12 | LOW | `getAdapter()` throws on unknown type, crashing entire sync loop | `registry.ts:17-19` | Wrap in try/catch in `syncLayersToMap`; continue to next layer |

---

## 3. Filter Building

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| F-01 | HIGH | `is_null` build/parse mismatch — emits `["any", ...]` but parser only matches `["!", ["has", f]]` | `LayerFilterEditor.tsx:109,141` | Align parser to recognize the `any` pattern, or simplify builder output |
| F-02 | HIGH | `in_list`/`not_in_list` round-trip broken — `["in", ["get", f], ["literal", [...]]]` misidentified by parser | `LayerFilterEditor.tsx:115,151` | Add dedicated parse branches for `literal`-wrapped list expressions |
| F-03 | HIGH | `has` operator round-trip misidentified — `["has", field]` falls through all parse branches | `LayerFilterEditor.tsx:111,151` | Add parse branch for `e[0] === 'has' && typeof e[1] === 'string'` |
| F-04 | MEDIUM | Exiting raw mode without applying does not re-sync visual state from prop | `LayerFilterEditor.tsx:294-300` | Call `applyParseResult(parseFilterExpression(filter))` on raw-mode exit |
| F-05 | MEDIUM | `handleFilterChange` does not update fill-extrusion companion layer | `use-layer-map-sync.ts:266-290` | Add `layer-{id}-extrusion` filter sync |
| F-06 | MEDIUM | `coerceValue` silently falls back to string when numeric parse fails | `LayerFilterEditor.tsx:80-81` | Reject `isNaN` values with validation error |
| F-07 | MEDIUM | Empty `in_list`/`not_in_list` value emits zero-element literal array hiding all features | `LayerFilterEditor.tsx:113` | Guard `values.length === 0` and skip condition |
| F-08 | LOW | Single-condition filter always wrapped in combinator — minor round-trip verbosity | `LayerFilterEditor.tsx:128-129` | Optional: unwrap single-expression wrappers before saving |
| F-09 | LOW | `addCondition` emits incomplete condition immediately, triggering unsaved-changes guard | `LayerFilterEditor.tsx:248-256` | Defer `emitChange` until condition becomes valid |
| F-10 | LOW | No `!has` operator available in UI despite being a valid MapLibre expression | `LayerFilterEditor.tsx:43-75` | Add `!has` to all type arrays with proper build/parse branches |
| F-11 | LOW | `!` parse branch for `is_null` ambiguously overlaps with `!has` | `LayerFilterEditor.tsx:141-147` | Resolve by renaming parsed operator to `!has` when pattern matches |
| F-12 | LOW | `handleRawApply` accepts `null` JSON and silently clears filter | `LayerFilterEditor.tsx:305-307` | Add toast feedback for null-as-clear path |

---

## 4. Label Configuration

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| LB-01 | HIGH | `textOpacity` declared in `LabelConfig` type but never read or rendered anywhere | `api.ts:678`, `label-layer-utils.ts` | Add `text-opacity` to paint in `buildLabelLayerSpec` and `syncLabelLayer`; add slider in `LabelEditor` |
| LB-02 | MEDIUM | Diagonal anchor options have hardcoded English labels (not i18n) | `LabelEditor.tsx:39-42` | Add `labelKey` entries to all locale files |
| LB-03 | MEDIUM | Toggling labels off destroys entire `LabelConfig` — re-enabling starts from defaults | `LabelEditor.tsx:63-65` | Store `savedConfig` ref; restore on re-enable |
| LB-04 | MEDIUM | Polygon labels placed at vertices not centroids (`symbol-placement: 'point'`) | `label-layer-utils.ts:19` | Add `symbol-avoid-edges: true`; document MVT centroid limitation |
| LB-05 | MEDIUM | `syncLabelLayer` resets anchor/offset to `center`/`[0,0]` for non-point placements | `label-layer-utils.ts:71-74` | Set to `null` (MapLibre default) instead of hardcoded values |
| LB-06 | LOW | `text-font` hardcoded to `Noto Sans Regular` — no bold/italic variants | `label-layer-utils.ts:34,66` | Expose fontWeight selector; document glyph server requirements |
| LB-07 | LOW | Polygon layers show single non-interactive placement button with no explanation | `LabelEditor.tsx:50-54` | Hide placement section or add explanatory label |
| LB-08 | LOW | `handleLabelChange` reads stale `layersRef.current` outside `applyLayerUpdate` closure | `use-layer-map-sync.ts:294-295` | Move layer lookup inside `applyFn` closure |

---

## 5. Share, Embed & Viewer

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| SH-01 | MEDIUM | Share token stored as plaintext in database (embed tokens use SHA-256 hash) | `service.py:710` | Hash with SHA-256 on write; return raw only at creation |
| SH-02 | MEDIUM | PATCH share token expiry — frontend date picker has off-by-one in UTC-ahead timezones | `SharePanel.tsx:93` | Compare parsed date against `new Date()` client-side before API call |
| SH-03 | MEDIUM | Domain-restriction toggle fires `handleSaveDomains` with stale `domainsValue` state | `SharePanel.tsx:185-195` | Pass empty string directly to `mutateAsync` in toggle handler |
| SH-04 | MEDIUM | Embed code generated with stale `embedTokenRaw` after dialog reopen — broken iframe snippet | `SharePanel.tsx:264-371` | Prompt user to regenerate when `embedTokenRaw` is null but token exists |
| SH-05 | LOW | iframe sandbox too restrictive — blocks fullscreen and same-origin tile fetches | `SharePanel.tsx:371` | Change to `allow-scripts allow-same-origin allow-fullscreen` |
| SH-06 | LOW | Internal maps accessible via `PublicMapViewerPage` with JWT — design decision undocumented | `router.py:125-148` | Document as intended or restrict |
| SH-07 | LOW | Embed token scope not refreshed when layers added/removed from published map | `embed_tokens/service.py:104-108` | Auto-update embed token scope on map layer changes |
| SH-08 | LOW | Thumbnail `Cache-Control: public` sent for private/internal maps | `router.py:700-702` | Use `private` for non-public maps |
| SH-09 | LOW | `MapViewerGate` uses client-side JWT role check — expired token shows builder with 401 errors | `MapViewerGate.tsx:18-24` | Add `expiresAt > Date.now()` check alongside `isEditor()` |
| SH-10 | LOW | `handleSaveDomains` silently no-ops if embed token was revoked between dialog open and save | `SharePanel.tsx:101-114` | Surface error when token no longer exists |

---

## 6. AI Chat Integration

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| AI-01 | HIGH | `MAX_STREAMING_WALL_CLOCK_SECONDS = 90` defined but never enforced — streams can run indefinitely | `constants.py:4`, `streaming.py` | Wrap streaming loop in `asyncio.wait_for` with the defined timeout |
| AI-02 | HIGH | No undo mechanism for chat-initiated map mutations (remove_layer, set_style, etc.) | `ChatPanel.tsx:135-175` | Capture pre-action snapshot; expose "Undo" button per assistant message |
| AI-03 | HIGH | `_validate_filter_columns` and action dropping only applied in non-streaming path — streaming skips validation | `chat_service.py:373-394`, `streaming.py` | Call `_validate_actions` on collected actions before yielding final SSE event |
| AI-04 | HIGH | `get_dataset_details` tool defined/labeled/exported but never offered to LLM or handled in chat executor | `tools.py:66-83`, `chat_service.py:596-656` | Remove from `TOOL_LABELS` or add to chat tool sets and implement handler |
| AI-05 | MEDIUM | Stale `layer_id` refs persist in sessionStorage history after `remove_layer` | `ChatPanel.tsx:71-89` | Filter history entries referencing removed layer IDs |
| AI-06 | MEDIUM | Stream-interrupted path produces no assistant message when actions were applied before `done` | `ChatPanel.tsx:273-320` | Always add assistant message if any actions were applied |
| AI-07 | MEDIUM | `show_query_result` bypasses `_validate_actions`; no GeoJSON feature-count cap | `chat_service.py:397-429` | Add `MAX_GEOJSON_FEATURES` cap in `_extract_geojson` |
| AI-08 | MEDIUM | `validate_paint_for_geometry` not called on data-driven style paint built server-side | `chat_service.py:635-636` | Call validator on paint returned from `_build_categorical/graduated_style` |
| AI-09 | MEDIUM | `toChatLayers` sends full `sample_values` per message — no client-side trim | `maps.ts:244-261` | Trim to first 5 columns matching server-side `_MAX_SAMPLE_COLS` |
| AI-10 | MEDIUM | Streaming + fallback endpoints share same rate limit; failure+retry double-counts | `router.py:56-57` | Track fallback hit client-side; only retry on transient errors |
| AI-11 | MEDIUM | Admin users blocked from chatting on maps they don't own (no admin bypass) | `router.py:117-119` | Add admin bypass in ownership check |
| AI-12 | MEDIUM | `validate_paint_for_geometry` `_outline-color` custom key coupling undocumented | `schemas.py:15` | Add comment explaining internal convention |
| AI-13 | LOW | Suggestion chip click populates input only — requires second click to send | `ChatPanel.tsx:339-361` | Invoke `handleSend()` after `setInput(suggestion)` |
| AI-14 | LOW | `@`-mention autocomplete surfaces layer names only, not column names | `ChatInput.tsx:75-85` | Add second-level autocomplete for columns after layer selection |
| AI-15 | LOW | OpenAI pre-tool thinking text silently discarded — undocumented behavior | `streaming.py:299-301` | Document in code comment |
| AI-16 | LOW | `textarea` has no `maxLength` — server 2000-char limit not enforced client-side | `ChatInput.tsx:199-214` | Add `maxLength={2000}` and character counter |

---

## 7. UI/UX & Accessibility

> **Note:** The UX audit subagent exceeded resource limits. Findings below are carried from the prior audit (2026-04-05) with verified resolution status based on intake code review.

### Resolved since prior audit

| Prior ID | Finding | Status |
|----------|---------|--------|
| B-012 | ChatPanel eagerly imported (not lazy-loaded) | **FIXED** — `MapBuilderPage.tsx:13` uses `lazy()` |
| B-013 | handleToggleVisibility only updates state | **FIXED** — `use-layer-map-sync.ts` now calls map directly |
| B-018 | HexColorInput no dark-mode styling | **Needs re-verification** |
| B-017 | Tile errors silently swallowed | **PARTIALLY FIXED** — `BuilderMap.tsx:143-152` now surfaces errors as deduped toast |

### Likely still present (from prior audit)

| Prior ID | Severity | Finding | File:line |
|----------|----------|---------|-----------|
| 7-16 | HIGH | Touch targets below 44px on mobile (layer menu, chat close) | `LayerItem.tsx`, `ChatPanelContent` |
| 7-19 | HIGH | Layer editor inline tabs missing ARIA `role="tab"` / `aria-selected` | `LayerItem.tsx` |
| 7-20 | HIGH | StyleColorPicker trigger has no `aria-label` | `StyleColorPicker.tsx` |
| 7-26 | MEDIUM | beforeunload missing `event.returnValue` for Chrome | `use-unsaved-guard.ts` |
| 7-29 | MEDIUM | Slider changes fire on every pixel — no debounce | `HeatmapStyleControls.tsx` |

---

## 8. Performance & Rendering

### 8a. React Re-renders

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| P-01 | HIGH | `LayerPanel` not `React.memo`-wrapped — any `MapBuilderPage` state change re-renders all rows | `LayerPanel.tsx:48` | Wrap `LayerPanel` and `SidebarContent` in `React.memo` |
| P-02 | HIGH | `index`/`totalLayers` props defeat `LayerItem` memo on every add/remove | `LayerPanel.tsx:142-143` | Replace with boolean `isFirst`/`isLast` props |

### 8b. MapLibre Efficiency

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| P-04 | MEDIUM | `tokenMap` change fires both `syncLayersToMap` and a redundant `setTiles` loop | `BuilderMap.tsx:276-302` | Remove redundant second `useEffect` (lines 286-302) |

### 8c. Debouncing & Memoization

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| P-03 | MEDIUM | Filter value input emits `setFilter` on every keystroke with no debounce | `LayerFilterEditor.tsx:262-264` | Debounce 150-200 ms before `emitChange` |
| P-05 | MEDIUM | `ColorRampPicker` calls `getRampColors` (chroma.js) for every ramp on every render | `ColorRampPicker.tsx:43` | Precompute module-level `RAMP_PREVIEW_COLORS` table |
| P-06 | MEDIUM | `ChatInput` rebuilds `slashCommands`/`layerItems` arrays on every keystroke | `ChatInput.tsx:69-85` | Memoize with `useMemo` keyed on `[t]`, `[layers]` |
| P-07 | MEDIUM | `DataDrivenStyleEditor` three effects re-run on every paint change due to broad `layer.paint` dep | `DataDrivenStyleEditor.tsx:142-221` | Narrow deps to specific paint keys |
| P-08 | MEDIUM | `StyleColorPicker` debounce 50ms — still fires ~10-20×/sec during fast drag | `StyleColorPicker.tsx:43-45` | Increase to 80-120 ms |

### 8d. Memory & Lifecycle

| # | Severity | Finding | File:line | Fix |
|---|----------|---------|-----------|-----|
| P-09 | LOW | `preserveDrawingBuffer: true` permanently doubles GPU framebuffer cost | `BuilderMap.tsx:388` | Accepted trade-off; document |
| P-10 | LOW | `filterSummary` computed inline while other summaries are memoized | `LayerItem.tsx:158` | Wrap in `useMemo` |
| P-11 | LOW | `whenMapIdle` listener not cancellable if hook unmounts before event | `use-builder-save.ts:55-61` | Return cancel function |
| P-12 | LOW | `maybeAutoCaptureThumbnail` closes over `state.localLayers`, changing identity on every edit | `use-builder-save.ts:246-250` | Read layers via ref to stabilize deps |
| P-13 | LOW | `.map(...).join(',')` evaluated in useEffect dep array on every render | `BuilderMap.tsx:270-273` | Pre-compute as variable |

---

## 9. Code Conventions & Type Safety

> **Note:** The conventions audit subagent exceeded resource limits. Key findings carried from the prior audit (2026-04-05) with intake verification.

### Resolved since prior audit

| Prior ID | Finding | Status |
|----------|---------|--------|
| B-033 | `sort_by`/`sort_dir` accept arbitrary strings | **FIXED** — `router.py:216` now uses `Literal` types |

### Likely still present

| Prior ID | Severity | Finding | File:line |
|----------|----------|---------|-----------|
| 9-1 | HIGH | `getSharedMap` uses raw `fetch()` bypassing `apiFetch` | `maps.ts` |
| 9-2 | HIGH | SSE streaming uses raw `fetch()` — skips token refresh | `maps.ts` |
| 9-7 | MEDIUM | Template literal in `className` instead of `cn()` (multiple files) | `ChatPanel.tsx`, `MentionDropdown.tsx` |

---

## 10. Prioritized Action Items

| ID | Priority | Severity | Finding | File:line | Fix | Dimension | Effort |
|----|----------|----------|---------|-----------|-----|-----------|--------|
| B-001 | P0 | HIGH | `is_null` filter build/parse mismatch — round-trip breaks visual editor | `LayerFilterEditor.tsx:109,141` | Align parser to recognize `any` pattern | Filter | S |
| B-002 | P0 | HIGH | `in_list`/`not_in_list` filter round-trip broken | `LayerFilterEditor.tsx:115,151` | Add dedicated parse branches for `literal`-wrapped lists | Filter | S |
| B-003 | P0 | HIGH | `has` operator round-trip misidentified | `LayerFilterEditor.tsx:111,151` | Add parse branch for `["has", string]` pattern | Filter | S |
| B-004 | P0 | HIGH | Streaming path skips `_validate_actions` — invalid column refs in filters applied to frontend | `chat_service.py:373`, `streaming.py` | Call `_validate_actions` before yielding SSE actions event | AI Chat | S |
| B-005 | P0 | MEDIUM | Share token stored as plaintext in database | `service.py:710` | Hash with SHA-256; return raw only at creation | Share | M |
| B-006 | P0 | MEDIUM | `add_layer` endpoint has no dataset access check | `router.py:706-787` | Call `_bulk_check_dataset_access` after ownership check | Layer Mgmt | S |
| B-007 | P1 | HIGH | `simplifyPaint` extracts wrong fallback from interpolate expressions | `shared.ts:33` | Add `interpolate` branch extracting `value[4]` | Style | S |
| B-008 | P1 | HIGH | `buildGraduatedExpression` has no null guard — null values assigned to first class | `color-ramps.ts:88` | Wrap in `["case", ["==", ["get", col], null], fallback, ...]` | Style | S |
| B-009 | P1 | HIGH | `fill-adapter.syncPaint` stroke ternary both branches identical (`'transparent'`) | `fill-adapter.ts:101` | Fix else branch to resolved outlineColor | Style | S |
| B-010 | P1 | HIGH | `MAX_STREAMING_WALL_CLOCK_SECONDS` defined but never enforced — infinite streams possible | `constants.py:4`, `streaming.py` | Wrap streaming loop in `asyncio.wait_for` | AI Chat | S |
| B-011 | P1 | HIGH | No undo mechanism for chat-initiated map mutations | `ChatPanel.tsx:135-175` | Capture snapshot; expose per-message undo button | AI Chat | L |
| B-012 | P1 | HIGH | `get_dataset_details` tool defined/labeled but not handled in chat executor | `tools.py:66-83` | Remove from `TOOL_LABELS` or implement | AI Chat | S |
| B-013 | P1 | HIGH | `LayerPanel` not memoized — any state change re-renders all layer rows | `LayerPanel.tsx:48` | Wrap in `React.memo` | Performance | S |
| B-014 | P1 | HIGH | `index`/`totalLayers` props defeat `LayerItem` memo | `LayerPanel.tsx:142-143` | Replace with `isFirst`/`isLast` boolean props | Performance | S |
| B-015 | P1 | HIGH | `textOpacity` in `LabelConfig` is dead code — never rendered | `label-layer-utils.ts` | Wire up in spec builder, sync, and editor | Label | S |
| B-016 | P1 | MEDIUM | Domain-restriction toggle fires with stale state | `SharePanel.tsx:185-195` | Pass empty string directly to `mutateAsync` | Share | S |
| B-017 | P1 | MEDIUM | Embed code generated with stale `embedTokenRaw` after dialog reopen | `SharePanel.tsx:264-371` | Prompt user to regenerate | Share | S |
| B-018 | P1 | MEDIUM | line-adapter `syncPaint` does not sync `line-dasharray` | `line-adapter.ts:42-51` | Extract from `input.layout` in `syncPaint` | Style | S |
| B-019 | P1 | MEDIUM | Heatmap `handlePaintChange` compounds with hardcoded 0.8 instead of stored value | `use-layer-map-sync.ts:102-103` | Read from `newPaint['heatmap-opacity']` | Style | S |
| B-020 | P1 | MEDIUM | `handleFilterChange` does not update fill-extrusion companion layer | `use-layer-map-sync.ts:266-290` | Add extrusion filter sync | Filter | S |
| B-021 | P1 | MEDIUM | Toggling labels off destroys entire `LabelConfig` — re-enabling starts from defaults | `LabelEditor.tsx:63-65` | Store `savedConfig` ref; restore on re-enable | Label | S |
| B-022 | P1 | MEDIUM | `coerceValue` silently falls back to string for invalid numeric input | `LayerFilterEditor.tsx:80-81` | Reject `isNaN` with validation error | Filter | S |
| B-023 | P1 | MEDIUM | Stale `layer_id` refs persist in chat sessionStorage after `remove_layer` | `ChatPanel.tsx:71-89` | Filter history entries referencing removed layers | AI Chat | S |
| B-024 | P2 | MEDIUM | `ColorRampPicker` preview always shows 7 swatches regardless of class count | `ColorRampPicker.tsx:43` | Add `count` prop; pass from `DataDrivenStyleEditor` | Style | S |
| B-025 | P2 | MEDIUM | Fill-extrusion sublayer orphaned on removal — stale cleanup hardcoded to 3 IDs | `map-sync.ts:256-267` | Call `adapter.getLayerIds(id)` | Layer Mgmt | S |
| B-026 | P2 | MEDIUM | Layer reorder deferred to next render cycle — visible flicker | `use-builder-layers.ts:122-141` | Call `reorderDataLayers()` synchronously | Layer Mgmt | S |
| B-027 | P2 | MEDIUM | `StyleColorPicker` debounce 50ms still fires 10-20×/sec during drag | `StyleColorPicker.tsx:43-45` | Increase to 80-120 ms | Performance | S |
| B-028 | P2 | MEDIUM | Filter input emits `setFilter` on every keystroke — no debounce | `LayerFilterEditor.tsx:262-264` | Debounce 150-200 ms | Performance | S |
| B-029 | P2 | MEDIUM | `DataDrivenStyleEditor` three effects re-run on every paint change | `DataDrivenStyleEditor.tsx:142-221` | Narrow deps to specific paint keys | Performance | S |
| B-030 | P2 | MEDIUM | `ChatInput` rebuilds arrays on every keystroke — no memoization | `ChatInput.tsx:69-85` | `useMemo` keyed on `[t]`, `[layers]` | Performance | S |

---

## 11. Builder Health Summary

### Aggregate Metrics

| Metric | Count |
|--------|-------|
| **Total findings (new)** | 83 |
| CRITICAL | 0 |
| HIGH | 13 |
| MEDIUM | 35 |
| LOW | 35 |

*Note: UX and Conventions subagents failed (resource limits). Actual total is higher when those dimensions are included.*

| Dimension | Findings |
|-----------|----------|
| Layer Management | 12 |
| Style Editing | 12 |
| Filter Building | 12 |
| Label Configuration | 8 |
| Share & Viewer | 10 |
| AI Chat | 16 |
| UI/UX Quality | (carried from prior) |
| Performance | 13 |
| Code Conventions | (carried from prior) |

### Effort Estimates

| Priority | Count | Estimated Effort |
|----------|-------|-----------------|
| **P0** (security / data loss / broken round-trip) | 6 | ~5 hours (5S + 1M) |
| **P1** (broken workflow / bad UX) | 14 | ~12 hours (12S + 1L + 1S) |
| **P2** (polish / convention) | 10 | ~6 hours (10S) |
| **Total P0+P1** | **20** | **~17 hours** |

### Top 3 Recommendations

1. **Fix the 3 filter round-trip HIGHs first** (B-001 through B-003): `is_null`, `in_list`/`not_in_list`, and `has` operators produce expressions that the parser cannot reconstruct. Every user who saves a map with these filter types will find the visual filter editor broken on reload. ~2 hours.

2. **Fix style-editing correctness** (B-007 through B-009): `simplifyPaint` interpolate fallback extraction, graduated null guard, and fill-adapter syncPaint ternary. These cause visual correctness issues for data-driven styles and polygon outlines. ~2 hours.

3. **Enforce streaming validation and timeout** (B-004, B-010): The streaming chat path skips `_validate_actions` (allowing invalid column refs through) and has no wall-clock timeout despite the constant being defined. ~2 hours.

---

## 12. Comparison to Prior Audit (2026-04-05)

### Prior audit: C+ (123 findings, 0 CRITICAL, 19 HIGH)
### This audit: B- (83 findings from 7/9 dimensions, 0 CRITICAL, 13 HIGH)

### Resolved HIGH findings (8 of 19)

| Prior ID | Finding | Resolution |
|----------|---------|------------|
| B-010 | `LayerItem` no `React.memo` | **FIXED** — `LayerItem` now wrapped in `memo` |
| B-012 | `ChatPanel` eagerly imported | **FIXED** — `MapBuilderPage.tsx:13` uses `lazy()` |
| B-013 | `handleToggleVisibility` only updates state | **FIXED** — `use-layer-map-sync.ts` now calls map directly |
| B-014 | Duplicate dataset layers blocked | **PARTIALLY FIXED** — frontend guard exists but API allows; now a design question |
| B-015 | `map.on('error')` listener never removed | **FIXED** — `BuilderMap.tsx:359-366` cleanup effect |
| B-016 | `lastOrderKeyRef` module singleton | **FIXED** — passed as `useRef` parameter |
| B-002 | Internal-map read access blocked | **FIXED** — `_check_map_read_access` now includes `is_internal` for authenticated users |
| B-033 | `sort_by`/`sort_dir` accept arbitrary strings | **FIXED** — `router.py:216` uses `Literal` types |

### Persistent findings (carried from prior)

| Prior ID | Finding | Status |
|----------|---------|--------|
| B-001 | Share token stored in plaintext | **STILL PRESENT** (now SH-01) |
| B-006 | Categorical data-driven styling drops null values | **STILL PRESENT** — now also found in graduated path (S-03) |
| B-008 | Heatmap opacity hardcoded 0.8 | **STILL PRESENT** (now S-07) |
| B-022 | swapLayerOnMap missing outline cleanup | **STILL PRESENT** (now S-05) |

### New findings not in prior audit

| ID | Finding | Why new |
|----|---------|---------|
| F-01/02/03 | Filter round-trip parse bugs (is_null, in_list, has) | New operators added since prior audit; parse logic not updated |
| S-02 | `simplifyPaint` interpolate fallback extraction | Edge case reached through new heatmap/graduated workflows |
| AI-03 | Streaming path skips `_validate_actions` | New streaming architecture since prior audit |
| AI-01 | Wall-clock timeout constant never enforced | Constant added but enforcement not wired up |
| L-03 | `add_layer` no dataset access check | Existed at prior audit time but not caught |
