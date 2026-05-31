# Map Builder Audit — 2026-05-30

> **Remediation status (2026-05-31):** All P1 findings fixed on branch
> `builder-audit-fixes-v2` (single commit `b561d67f`), branched off `main` after the
> concurrent milestone-1162 widget→plugin rename landed. Fixes: **B-001/B-002** (ChatAction
> rows/columns/row_count/truncated + dataset_name + OpenAPI/FE-type regen) — plus a deeper
> latent bug surfaced during verification: the AI inline data-table renderer keyed rows as
> objects, but the real backend contract is `list[list]` row arrays paired with a `columns`
> array, so even once the fields flowed the table would have rendered empty; `ChatPanel`, the
> frontend type, and the 1135 test fixtures were corrected to the true contract. **B-003**
> (filter-count `layer-${id}` prefix), **B-004/B-005/B-006** (line-arrow companion in
> visibility/bulk/filter), **B-008/B-009** (label-change symbol/heatmap guards), **B-031**
> (duplicate inherits visibility). **B-018/B-019/B-028/B-029** had already landed on `main`
> via an earlier merge (`e5791042`). Regression tests added: backend ChatAction round-trip;
> frontend filter-count prefix. **Verification:** frontend typecheck 0; builder+viewer vitest
> **1454/1454**; backend chat suite **38/38**; OpenAPI snapshot in sync; eslint/ruff clean on
> changed files. **Live Playwright MCP smoke (2026-05-31, public showcase map
> `c39be324`):** builder loads with **zero console errors** on the post-1162-rename + fixes
> bundle; the served `use-layer-map-sync` module confirmed to contain the arrow-companion fix
> (not a stale bundle); `setFilter` apply→clear round-trips cleanly on a line layer; the
> unsaved-changes `beforeunload` guard fires correctly; legend renders with the "plugin"
> rename live. The showcase map was **not saved** (in-memory toggle discarded via the guard;
> no test data mutated). **One unresolved observation (carry-forward, NOT attributable to this
> change):** the layer-row eye toggle flipped React dirty-state (`aria-pressed` + "Unsaved
> changes") but the resolved MapLibre layer's `visibility` stayed `visible` for the Blue Line
> fill/outline pair. My B-004 edit only *adds* an `arrowId` line to an already-working
> visibility block, so it cannot regress fill/outline toggling; the `use-layer-map-sync` /
> `use-builder-layers` visibility unit suites pass. The most likely cause is the fiber-resolved
> Map not being the live render target (instrumentation artifact) or a pre-existing builder
> sync quirk — needs a focused `/gsd-debug` session, filed as **B-041 (P2)**. Remaining
> P2/LOW items (AI undo, embed Referer fallback, perf memoization, misc UX/token, B-041) are
> documented below, untouched.

## Scorecard

| Dimension | Grade |
| --------- | ----- |
| 1. Layer Management (2×) | B |
| 2. Style Editing (2×) | B |
| 3. Filter Building | B |
| 4. Label Configuration | B |
| 5. Share, Embed, Viewer & Terrain (2×) | B+ |
| 6. AI Chat Integration | C |
| 7. UI/UX & Accessibility | B |
| 8. Performance & Rendering | B |
| 9. Code Conventions & Type Safety | A− |
| **Overall builder health** | **B−** |

## Executive Summary

The builder is structurally sound and ships strong backend enforcement: the share/embed/edition surface was verified to have **no private-data leak and no edition-gate bypass** (3-layer enforcement: schema validator → service → frontend gate), token scoping is correct, and conventions are clean (0 production `any`, auth-gated mutations, `response_model` everywhere). The single most serious issue is in **AI chat integration**: the backend `ChatAction` Pydantic model silently drops the `rows`/`columns`/`row_count`/`truncated` fields, so the AI inline data-table card **never renders** (CRITICAL, confirmed), and it lacks `dataset_name`, so `add_layer` staging chips show raw UUIDs (HIGH, confirmed). The most common real bug pattern across dimensions is the **missing `-arrow` companion sublayer** in the line-arrow render mode — visibility toggle, bulk visibility, and filter application all skip it. Top recommendation: fix the chat `ChatAction` schema and the arrow-companion gaps first; both are small, high-confidence, high-impact changes.

## Scope, Environment, and Verification

- **Scope:** Full audit — all 9 dimensions. Args: none (full).
- **Repo state:** branch `main` @ `bf6c50a4` (mid plugin-rename milestone 1161; `widget`→`plugin` rename in progress — Settings "Widgets" section and `/widget-audit` references reflect the pending rename, not findings).
- **Stack:** UP and healthy — `frontend` localhost:8080 → 200, all 5 containers healthy (api mapped to `:8001`, db `:5434`, titiler, worker). The initial `:8000` probe 404'd only because the API host-port is `:8001`.
- **Execution model:** 9 dimension subagents (read-only, full-file reads) + orchestrator verification of all CRITICAL/HIGH findings by direct file read.
- **Subagent 7 Phase B (live Playwright MCP visual verification):** deferred to the orchestrator remediation pass (executor/dimension subagents lack `mcp__playwright__*` access — see project memory). Phase A (code-level UX) ran fully; live dark-mode/responsive/keyboard checks are listed in §7 as orchestrator-driven follow-ups.
- **Test gates available but not yet run in this audit pass:** `npm run e2e:smoke:builder`, `e2e:smoke:builder-hardening`, `e2e:smoke:perf`, `frontend npm run test`, `backend uv run pytest`. These are reserved for the remediation verification pass.

---

## 1. Layer Management — Grade B

1. **[MEDIUM]** `handleToggleVisibility` omits the `-arrow` companion — `use-layer-map-sync.ts:77-88`. Toggling a line layer in arrow render mode leaves the arrow symbols visible while everything else hides. **Fix:** add `layer-${layerId}-arrow` to the toggled ids. *(orchestrator-confirmed)*
2. **[MEDIUM]** `handleBulkVisibility` omits `-arrow` — `use-builder-layers.ts:440-456`. Arrow layers survive a bulk hide. **Fix:** add `layer-${id}-arrow` to the `ids` array.
3. **[MEDIUM]** `handleDeleteGroup` mutates local state but never calls `removePerLayerCompanions` — `use-builder-layers.ts:405-416`. Group children's MapLibre paint layers linger as ghost visuals until the next React-driven sync. **Fix:** collect child ids from `layersRef.current` and call `removePerLayerCompanions(map, childIds)` before `setLocalLayers`.
4. **[LOW]** `handleDeleteGroup` is draft-only (children deleted on server only at Save) whereas single `handleRemove` persists immediately — `use-builder-layers.ts:405-416`. Inconsistent persistence semantics. **Fix:** document the draft-until-Save contract in the handler, or route child ids through `handleBulkDelete`.
5. **[LOW]** `buildDuplicateRenderingInput` hard-codes `visible: true` — `builder-layer-mutations.ts:84`. Duplicating a hidden layer yields a visible copy. **Fix:** `visible: layer.visible ?? true`.
6. **[LOW]** Duplicate rendering lands at the bottom of the stack (`max(sort_order)+1`) while new datasets land at top — `builder-layer-mutations.ts:77`. Surprising placement. **Fix:** place at `layer.sort_order + 1` (directly below original) or document the policy.
7. **[LOW]** `removeStaleSourcesAndLayers` infers layer id from a deduped shared `source-data-<table>` id via string replace — `map-sync.ts:865-896`. Wrong id for shared sources; source can leak if all sharers are removed at once (e.g. group delete). **Fix:** maintain a source→layerIds map instead of string-deriving the id.
8. **[LOW]** Empty rename silently reverts to `dataset_name` with no user feedback — `use-builder-layers.ts:232-238`. **Fix:** reflect the reverted name in the input before blur (optional toast).
9. **[LOW]** `HistoryPanel` reads as an interactive timeline but has no restore affordance — `HistoryPanel.tsx:1-154`. Implies recoverability that doesn't exist. **Fix:** label it as a read-only audit log.

**Verified OK:** sidebar↔MapLibre order invariant; single-remove/bulk-delete sublayer cleanup (incl. `-arrow`, `-colorrelief`); visibility restores real style; duplicate independence; drag-reorder moves all sublayers; raster/VRT capability gate (opacity-only); group rows excluded from tile/style ops and save payload; AI remove draft-only vs manual remove persisted; ephemeral cleanup complete.

---

## 2. Style Editing — Grade B

1. **[MEDIUM]** `_hypso-enabled` / `_hypso-ramp` absent from `CUSTOM_PAINT_PROPS` (shared.ts:6-13) and backend `LEGACY_BUILDER_PAINT_KEYS` (schemas.py:23-45). The hillshade path reads them directly so there's no runtime crash, but they accumulate in `paint` JSONB and would break `AdvancedJsonEditor`/`validateStyleMin` for DEM layers. **Fix:** add `_hypso-enabled`/`_hypso-ramp` to `CUSTOM_PAINT_PROPS` and to `LEGACY_BUILDER_PAINT_KEYS`.
2. **[MEDIUM]** `AdvancedJsonEditor` receives raw `paint` including builder-private `_`-prefixed keys — `LayerStyleEditor.tsx:434`, `AdvancedJsonEditor.tsx:96-103`. Any layer with `_outline-color`/`_stroke-disabled`/`_height_column` makes `validateStyleMin` reject on Apply with a confusing "unknown property" error. **Fix:** strip `CUSTOM_PAINT_PROPS` + `_`-prefixed keys before passing to `AdvancedJsonEditor`, or pre-filter inside `validatePropertyBlock`.
3. **[MEDIUM]** Null-guard `['==', ['get', col], null]` can't distinguish missing-key from JSON-null — `color-ramps.ts:69,92,129`. Features with real `null` always get the fallback color. **Fix:** use `['!', ['has', col]]` to target only missing keys (or document the intentional coalescing).
4. **[LOW]** Hillshade accent-color editor default `#D4A97A` ≠ adapter default `#000000` — `DEMEditorScene.tsx:210` vs `hillshade-adapter.ts:11`. Picker shows warm-tan while map renders black on first load. **Fix:** align the `getString` fallback to `HILLSHADE_PAINT_DEFAULTS`.
5. **[LOW]** `StyleColorPicker` silently drops non-6-digit-hex input (rgba/hsl/8-digit/named) — `StyleColorPicker.tsx:16,48-51`. No error shown; valid MapLibre colors are lost. **Fix:** show an inline validation message on regex miss.
6. **[LOW]** Setting `fill-pattern` doesn't drop `fill-color` from the persisted paint — `FillEditor.tsx:76-77`, `LayerStyleEditor.tsx:215-225`. Dead key remains (no render bug; clearMissing handles runtime). **Fix:** remove `fill-color` when a pattern id is set.
7. **[LOW]** `circle-radius` slider min is `1`, blocking valid sub-pixel hairline dots — `CircleEditor.tsx:44`. **Fix:** lower `min` to `0.1`.
8. **[LOW]** `registry.getAdapter()` silently falls back to `circleAdapter` for unknown types (DEV-only warn) — `registry.ts:22-28`. Silent spec violation in prod. **Fix:** return `null`/throw for unknown types and have callers skip sync.

**Verified OK:** no OKLCH reaches MapLibre paint; line-cap/join enums spec-valid; categorical/graduated `match`/`step` arity correct; mode switches remove companion layers + stale keys; `line-gradient` cleared on solid; raster `_colormap`/`_stretch`/`_pmin` allowlisted; color-relief emits native `color-relief` with `_hypso-*` stripped at the hillshade path.

---

## 3. Filter Building — Grade B

Operator coverage: all of `==,!=,>,<,>=,<=,is_null,has,in_list,not_in_list,contains` emit **expression form** (`["op", ["get", "prop"], value]`), AND→`["all"]`, OR→`["any"]`. No legacy positional form generated. Opaque filters fall back to a raw-JSON edit mode.

1. **[HIGH]** `useFilteredFeatureCount` queries `map.getLayer(layer.id)` / `queryRenderedFeatures({layers:[layer.id]})` with the **UUID**, not the MapLibre id `layer-${layer.id}` — `use-filtered-feature-count.ts:46,51`. `layerExistsOnMap` is always false → hook always returns `null` → the "0 features — check your filter" empty-state hint never fires. Tests mask it (mock `getLayer` returns truthy; fixture id `layer-1`). **Fix:** use `` `layer-${layer.id}` `` at both lines. *(orchestrator-confirmed; code comment contradicts the code)*
2. **[MEDIUM]** `handleFilterChange` doesn't apply the filter to the `-arrow` sublayer — `use-layer-map-sync.ts:360-388`. Arrow symbols show for filtered-out features. **Fix:** add `map.setFilter(layer-${id}-arrow, filter)` alongside the other sublayers.
3. **[LOW]** `ActiveFilterChips.summarizeFilter` mislabels the `contains` operator as `"<value> in (…)"`; the substring branch at line 69 is dead — `ActiveFilterChips.tsx:54-71`. **Fix:** detect `["in", value, ["get", f]]` before calling `extractField`.

**Verified OK:** remove-all → `setFilter(null)`; empty-value conditions dropped; numeric `to-number` safe-wrap with no double-wrap; round-trip parse↔build for all operators; property dropdown from dataset schema; setFilter (not tile re-fetch) applied to fill/outline/extrusion/label/cluster.

---

## 4. Label Configuration — Grade B

1. **[MEDIUM]** `handleLabelChange` creates a spurious companion `*-label` layer for symbol-mode point layers (no `render_mode==='symbol'` guard) — `use-layer-map-sync.ts:395-444`. The next `syncLayersToMap` removes it → one-cycle duplicate-label flicker. **Fix:** for symbol mode, update the primary symbol layer's text via owned-layout/paint sync instead of adding a companion.
2. **[MEDIUM]** `handleLabelChange` lacks a heatmap guard — `use-layer-map-sync.ts:412-416`. AI `set_label` bypasses the UI gate and transiently adds a label layer to a heatmap. **Fix:** `if (render_mode==='heatmap') return;`.
3. **[LOW]** `StackRow` `hasLabels` badge suppresses for symbol mode even though symbol layers with `label_config.column` DO render text — `StackRow.tsx:144`. Badge misrepresents state. **Fix:** drop `&& renderMode !== 'symbol'`.
4. **[LOW]** `symbol-placement` not in `SYMBOL_OWNED_LAYOUT_PROPERTIES` — `symbol-adapter.ts:11-26`. Harmless today (default `point`) but won't reset if ever set non-default. **Fix:** add it and set `'point'` explicitly in `symbolLayout()`.
5. **[LOW]** `symbol-avoid-edges: true` on polygon-centroid (point-placement) labels can suppress labels near tile edges — `label-layer-utils.ts:51`. **Fix:** remove for point-placement fill labels or make configurable.
6. **[LOW]** `buildLabelLayerSpec` vs `syncLabelLayer` diverge on non-point `text-anchor`/`text-offset` defaults — `label-layer-utils.ts:53-57` vs `87-90`. Functionally equal today; fragile. **Fix:** make both explicit/symmetric.
7. **[INFO]** Backend stores `label_config` as unvalidated `dict|None` (schemas.py:478-480); placement clamp is client-only. **Fix:** add a backend validator (or document the client clamp as sole enforcement).

**Verified OK:** Symbols-vs-Labels architecture correct across `renderAs.ts`/`symbol-adapter.ts`/`LayerEditorPanel.tsx`; text-anchor/symbol-placement enums spec-valid; halo color/width supported; companion `*-label` parity for filters/visibility/zoom; Labels tab hidden for heatmap/raster/DEM.

---

## 5. Share, Embed, Viewer & Terrain — Grade B+

**No CRITICAL/HIGH. No edition-gate bypass and no private-data leak found.** Edition gating is enforced at 3 layers; embed token scoping (`scoped_dataset_ids`) prevents cross-map leaks; tokens SHA-256 hashed (raw never persisted/logged); `token_hint` never builds URLs; CSP `frame-ancestors` derived per-token; iframe sandbox `allow-scripts` only (no `allow-same-origin`); tile tokens batch-fetched + mid-session refresh at 80% TTL.

1. **[MEDIUM]** Embed `allowed_origins` domain-lock falls back to forgeable `Referer` when `Origin` is absent — `embed_tokens/service.py:71-83` (used at :303). Weakens (not bypasses) the restriction for header-stripped requests. **Fix:** treat as best-effort defense-in-depth (document), or require `Origin` for domain-locked tokens.
2. **[MEDIUM]** Domain-locking is meaningless for maps whose layers are all **public** (tiles anonymously fetchable regardless of origin) — `tiles/router.py:415-425,1076-1086`. **Fix:** clarify in SharePanel copy that domain restriction only meaningfully scopes non-public layers.
3. **[LOW]** `S5-09` — `get_shared_map` returns layer `display_name`/`table_name`/`column_info` for non-public layers (tiles blocked, but names enumerable) — `service_public.py:355-370`. **Fix:** confirm `apply_visibility_filter` drops non-public rows for anonymous callers; add row-level exclusion if it only gates tiles. *(worth a quick confirm)*
4. **[LOW]** Embed `use_count`/`last_used_at` only increment on cache miss (~once/300s) — `embed_tokens/service.py:319-329`. Telemetry undercounts. **Fix:** increment on cache hit too, or document as sampled.
5. **[LOW]** `PublicViewerPage` accepts `?api_key=` and uses it to mint tile tokens on the public viewer — `PublicViewerPage.tsx:53,154`. Conflates API-key access with share access. **Fix:** confirm intentional; otherwise drop `api_key` plumbing from the public viewer.
6. **[LOW]** Embed-preview 8s `onLoad` timeout false-positives "Preview unavailable" on slow networks — `SharePanel.tsx:530-534`. **Fix:** key the error off a load `error` event, not a fixed timer; clear timer in `onLoad`.
7. **[LOW]** "Open in new tab" uses `/m/{rawToken}` while "Copy Link" copies the `/card` redirect URL — `SharePanel.tsx:806-822,835`. Meta-refresh-blocking clients dead-end on the card. **Fix:** add a visible `<noscript>` fallback link in the card HTML.
8. **[LOW]** Terrain `exaggeration` unvalidated server-side (render-time clamp protects the viewer) — backend `update_map` stores raw JSON. **Fix:** add a Pydantic bound on `MapTerrainConfig.exaggeration`.

**Verified OK:** visibility backend-enforced (anon→404 for non-public; share auto-revoke on downgrade); thumbnails PIL-verified + visibility-respecting; viewer renders via shared adapter registry (builder parity), no edit controls, attribution visible; terrain toggle/restore + non-meter unit warning + hillshade-vs-terrain advisory.

---

## 6. AI Chat Integration — Grade C

1. **[CRITICAL]** `show_query_result` inline table **never renders** — `ChatAction` (schemas.py:365-388) has no `rows`/`columns`/`row_count`/`truncated`; `_collect_chat_action` builds them (chat_actions.py:247-255) but `ChatAction(**a)` drops them (`extra='ignore'`), and `model_dump(exclude_none=True)` emits `{type}` only (streaming.py:266,522). The Phase-1135 AI-08 data card (`ChatPanel.tsx:737`) reads always-`undefined` `rows`. **Fix:** add `rows/columns/row_count/truncated` fields to `ChatAction`. *(orchestrator-confirmed)*
2. **[HIGH]** `add_layer` staging chips show raw UUID — `ChatAction` lacks `dataset_name` (schemas.py:365); `buildChipText` reads `action.dataset_name ?? action.dataset_id` (ChatPanel.tsx:224). **Fix:** add `dataset_name` to backend `ChatAction` and populate it in `_collect_chat_action`. *(orchestrator-confirmed)*
3. **[MEDIUM]** Undo button stays enabled after accepting a staged destructive action in a mixed turn — `ChatPanel.tsx:445-473`. `mutatingActions` excludes `remove_layer` so `supportsUndo` stays true; undo then can't restore. **Fix:** on accept, set `supportsUndo=false` if any accepted action isn't undo-safe.
4. **[MEDIUM]** Undo re-add creates a new layer id; the following state-restore loop uses the stale old id → paint/filter/label restore no-ops — `ChatPanel.tsx:291-311`. **Fix:** thread a success callback through `onAddDataset` to capture the new id before restoring state.
5. **[MEDIUM]** SSE `error` event throws a plain `Error` → falls through to the non-streaming fallback, doubling the LLM call on model-side errors — `ChatPanel.tsx:492-552`. **Fix:** throw a typed sentinel for SSE errors and show an inline error instead of retrying.
6. **[LOW]** Dataset `sample_values` embedded in the system prompt without sanitization (layer names ARE sanitized) — `chat_service.py:217-225`. Prompt-injection surface. **Fix:** sanitize sample values like layer names.
7. **[LOW]** `handleUndo` skips paint restore when the snapshot paint was null — AI style change becomes permanent — `ChatPanel.tsx:299`. **Fix:** `onPaintChange(id, layer.paint ?? {})`.
8. **[LOW]** Non-admin users with `use_ai_chat` permission see a perpetual spinner (admin-only status query) — `use-ai-availability.ts:39`. **Fix:** expose a non-admin AI status or derive availability from the permission.
9. **[LOW]** `popup_config` sent in `toChatLayers` but dropped by `ChatMapLayer` (`extra='ignore'`) — `maps.ts:417` / schemas.py:318. **Fix:** add the field or stop sending it.
10. **[INFO]** `get_dataset_details` defined but not in `CHAT_TOOLS_ANTHROPIC` — tools.py:66,88. The chat LLM can't call it despite prompt references. **Fix:** add it to the chat tool list + dispatcher, or remove the prompt references.

**Scope note:** AI generation quality / `validate_paint_for_geometry` belong to `/ai-optimize`, not re-audited here.

---

## 7. UI/UX & Accessibility — Grade B

**Empty States:** ES-01 [LOW] chat empty state has no icon (`ChatPanel.tsx:675-695`); ES-02 [MEDIUM] "Add custom basemap" is a visible no-op stub (`MapBuilderPage.tsx:954`) — gate/disable it with a tooltip or remove.
**Loading States:** LS-01 [LOW] add buttons disable without a spinner (`DatasetSearchPanel.tsx:499,515`); LS-02 [LOW] hardcoded English `aria-label="Loading panel"` (`SceneSpinnerFallback.tsx:17`).
**Error States:** ER-01 [MEDIUM] map error toast doesn't name the failing layer (`BuilderMap.tsx:509`); ER-02 [LOW] `BasemapAppearanceControls.tsx` is dead code (no non-test importers).
**Keyboard:** KB-01 [MEDIUM] `BasemapPicker` dropdown has no Escape handler (`BasemapPicker.tsx:51-79`); KB-02 [LOW] `SublayerRow` tabIndex div has no `role` (`UnifiedStackPanel.tsx:469,486`); KB-03 [LOW] mobile rail buttons missing `type="button"` (`MapBuilderPage.tsx:1443`).
**Basemap Picker:** BP-01 [MEDIUM] grid thumbnails not `loading="lazy"` (`BasemapPicker.tsx:69-71`); BP-02 [LOW] basemap eye button permanently disabled (`UnifiedStackPanel.tsx:869`).
**Map Settings:** MS-01 [LOW] background swatch fallback `#ffffff` (`SettingsEditorScene.tsx:52`); MS-02 [LOW] Terrain section has no "add DEM" CTA.
**Unsaved Changes:** UC-01 [MEDIUM] guard dialog offers only Stay/Leave, no "Save and leave" (`BuilderDialogs.tsx:175-189`).
**Map Toolbar:** MT-01 [LOW] tooltip shortcuts (V/M/L) shown but not wired (`MapToolbar.tsx:50-67`).
**Interaction Feedback:** IF-01 [MEDIUM] `FillPatternPicker` previews hardcode `#6b7280` ×7 (dark-mode contrast) (`FillPatternPicker.tsx:26-51`); IF-02 [LOW] PNG export hardcodes light colors (intentional — document).
**Dark Mode (code-level):** DM-01 [MEDIUM][VISUAL] `BasemapGroupEditorScene.tsx:284` `hover:bg-[oklch(0.97_0.02_27)]` flashes near-white in dark mode → use `hover:bg-destructive/10`; DM-02/DM-03 [LOW][VISUAL] = MS-01 + IF-01 re-flagged for dark mode.
**Layout:** LA-01 [LOW] sidebar is fixed-width, no resize handle (intentional per UI-SPEC 1034 — document).

**Live (Playwright MCP) checks to run in remediation:** dark-mode render across all surfaces; responsive at 800/1100/1440px; focus-ring visibility; Tab order + Escape on BasemapPicker; drag preview; color-picker/slider real-time map preview; success toasts; basemap attribution update; "No basemap" state.

---

## 8. Performance & Rendering — Grade B

**React Re-renders:** RR-01 [MEDIUM] `selectedIds` Set identity changes on every toggle → all N rows re-render (`UnifiedStackPanel.tsx:1018,1047,1078`); RR-03 [MEDIUM] `terrainLayerKey` recomputed every render, unmemoized (`BuilderMap.tsx:416-421`); RR-04 [MEDIUM] `ColorRampPicker` runs `chroma.scale().colors()` up to ~36×/render unmemoized (`ColorRampPicker.tsx:43-44`); RR-05 [LOW] baseline layer clone on every clean render (`use-builder-save.ts:429-433`). *(RR-02 retracted — handlers are stable.)*
**MapLibre Efficiency:** ME-01 [LOW] raster style-config change does remove+re-add source even for paint-only changes (`use-layer-map-sync.ts:191-204`); ME-02 [LOW] `styleDiffing={false}` re-adds data layers on basemap switch (intentional — document) (`BuilderMap.tsx:1083`).
**Memory Leaks:** ML-01 [MEDIUM] anonymous `dataloading`/`idle` listeners never removed in cleanup (`BuilderMap.tsx:464-465` vs cleanup :1024-1036). *(ML-02/ML-03 verified clean.)*
**Bundle:** BND-01 [LOW] `LayerEditorPanel` eagerly imported though only shown when a layer is selected (`MapBuilderPage.tsx:53`). *(ChatPanel, DataDrivenStyleEditor, DatasetSearchPanel, editor scenes, StyleJsonDialog all correctly lazy.)*
**Debouncing:** DB-01 [LOW] hex text input not debounced (`StyleColorPicker.tsx:48-51`); DB-02 [LOW] opacity slider re-renders all of `LayerStyleEditor` at 60fps during drag (`LayerStyleEditor.tsx:177-196`). *(Filter/popup/data-driven/search/thumbnail debouncing all good.)*

---

## 9. Code Conventions & Type Safety — Grade A−

**No HIGH/CRITICAL. 0 production `any`.** All API calls funnel through `apiFetch()`; auth uses imperative `setTransformRequest` + `getState().token`; every mutating maps endpoint is auth-gated; `response_model` declared everywhere; dual-shape alias pattern followed.

- AC-01 [LOW] raw `fetch()` for the public basemap CDN URL (correct — not `/api/`; add a clarifying comment) — `BuilderMap.tsx:228`.
- Design tokens: DT-03 inline px typography (`LayerEditorPanel.tsx:294`); DT-05 `style={{maxWidth:200}}` (`UnifiedStackPanel.tsx:625`); DT-06 inline padding (`UnifiedStackPanel.tsx:905`); DT-07 [INFO] hardcoded amber OKLCH not tokenized (`FolderGroupRow.tsx:245`). (renderAs/thumbnail hex are exempt MapLibre/canvas colors.)
- CP-01 [LOW] template-literal `className` without `cn()` (`BuilderRail.tsx:206`).
- TS-02/TS-03 [LOW] `as unknown as StyleConfig` ×7 (`renderAs.ts`) + repeated `as Record<string,unknown>` style-config casts — add a typed accessor helper.
- EH-01 [LOW] silent thumbnail catch (`use-builder-save.ts:77`); EH-02 [LOW] silent cluster outer catch (`BuilderMap.tsx:354`); EH-03 [INFO] bare `catch {}` in `SharePanel` doesn't distinguish 403 vs 422.
- BC-04 [INFO] `MapUpdate` lacks `extra="forbid"` (schemas.py:630) — unknown PUT fields silently ignored.

---

## 10. Prioritized Action Items

| ID | Pri | Sev | Finding | File:line | Fix | Dim | Effort |
| -- | --- | --- | ------- | --------- | --- | --- | ------ |
| B-001 | P1 | CRITICAL | AI inline data-table never renders (ChatAction drops rows/columns) | schemas.py:365-388 | Add `rows/columns/row_count/truncated` to `ChatAction` | 6 | S |
| B-002 | P1 | HIGH | add_layer staging chips show UUID (no dataset_name) | schemas.py:365 + ChatPanel.tsx:224 | Add `dataset_name` to `ChatAction`, populate in `_collect_chat_action` | 6 | S |
| B-003 | P1 | HIGH | "0 features" filter hint never fires (UUID vs layer-id) | use-filtered-feature-count.ts:46,51 | Use `layer-${layer.id}` in both calls | 3 | S |
| B-004 | P1 | MEDIUM | Visibility toggle skips `-arrow` companion | use-layer-map-sync.ts:77-88 | Add `layer-${id}-arrow` | 1 | S |
| B-005 | P1 | MEDIUM | Bulk visibility skips `-arrow` | use-builder-layers.ts:440-456 | Add `layer-${id}-arrow` to ids | 1 | S |
| B-006 | P1 | MEDIUM | Filter change skips `-arrow` sublayer | use-layer-map-sync.ts:360-388 | `setFilter` on `-arrow` | 3 | S |
| B-007 | P1 | MEDIUM | Group delete leaves ghost MapLibre layers | use-builder-layers.ts:405-416 | `removePerLayerCompanions(map, childIds)` before setLocalLayers | 1 | M |
| B-008 | P1 | MEDIUM | handleLabelChange adds spurious companion on symbol layers | use-layer-map-sync.ts:395-444 | Guard symbol mode; update primary symbol text | 4 | M |
| B-009 | P1 | MEDIUM | handleLabelChange lacks heatmap guard (AI bypass) | use-layer-map-sync.ts:412-416 | `if render_mode==='heatmap' return` | 4 | S |
| B-010 | P1 | MEDIUM | AdvancedJsonEditor rejects on builder `_`-keys | LayerStyleEditor.tsx:434 + AdvancedJsonEditor.tsx:96-103 | Strip `_`-prefixed/CUSTOM_PAINT_PROPS before validate | 2 | M |
| B-011 | P1 | MEDIUM | `_hypso-*` keys not allowlisted | shared.ts:6-13 + schemas.py:23-45 | Add to CUSTOM_PAINT_PROPS + LEGACY_BUILDER_PAINT_KEYS | 2 | S |
| B-012 | P1 | MEDIUM | AI undo: new layer id breaks state restore | ChatPanel.tsx:291-311 | Capture new id via add callback before restore | 6 | M |
| B-013 | P1 | MEDIUM | AI undo enabled after destructive mixed turn | ChatPanel.tsx:445-473 | Set supportsUndo=false on non-undo-safe accept | 6 | S |
| B-014 | P1 | MEDIUM | SSE error → non-streaming retry doubles LLM call | ChatPanel.tsx:492-552 | Typed SSE-error sentinel; inline error, no retry | 6 | M |
| B-015 | P1 | MEDIUM | "Add custom basemap" visible no-op | MapBuilderPage.tsx:954 | Disable+tooltip or remove until implemented | 7 | S |
| B-016 | P1 | MEDIUM | BasemapPicker no Escape handler | BasemapPicker.tsx:51-79 | Add Escape onKeyDown → setOpen(false) | 7 | S |
| B-017 | P1 | MEDIUM | Map error toast doesn't name failing layer | BuilderMap.tsx:509 | Match event.sourceId → layer name in toast | 7 | M |
| B-018 | P2 | MEDIUM | DM-01 oklch hover flashes white in dark mode | BasemapGroupEditorScene.tsx:284 | `hover:bg-destructive/10` | 7 | S |
| B-019 | P2 | MEDIUM | FillPatternPicker previews hardcode #6b7280 | FillPatternPicker.tsx:26-51 | `currentColor`/`var(--muted-foreground)` | 7/9 | S |
| B-020 | P2 | MEDIUM | selectedIds Set re-renders all stack rows | UnifiedStackPanel.tsx:1018-1078 | Stable membership / array-based selection | 8 | M |
| B-021 | P2 | MEDIUM | terrainLayerKey unmemoized | BuilderMap.tsx:416-421 | `useMemo` | 8 | S |
| B-022 | P2 | MEDIUM | ColorRampPicker recomputes ramps every render | ColorRampPicker.tsx:43-44 | Module-level memo `Map<name:count, colors>` | 8 | S |
| B-023 | P2 | MEDIUM | dataloading/idle listeners leak | BuilderMap.tsx:464-465 | Store refs, `map.off` in cleanup | 8 | S |
| B-024 | P2 | MEDIUM | Embed allowed_origins Referer fallback | embed_tokens/service.py:71-83 | Document best-effort or require Origin | 5 | S |
| B-025 | P2 | LOW | S5-09 non-public layer metadata enumerable | service_public.py:355-370 | Confirm/row-exclude non-public layers for anon | 5 | M |
| B-026 | P2 | LOW | Null-guard can't distinguish missing vs null | color-ramps.ts:69,92,129 | `['!',['has',col]]` | 2 | S |
| B-027 | P2 | LOW | StyleColorPicker drops non-hex silently | StyleColorPicker.tsx:48-51 | Inline validation message | 2 | S |
| B-028 | P2 | LOW | circle-radius min=1 blocks sub-pixel | CircleEditor.tsx:44 | min=0.1 | 2 | S |
| B-029 | P2 | LOW | registry silent circle fallback | registry.ts:22-28 | Return null/throw on unknown | 2 | S |
| B-030 | P2 | LOW | hillshade accent default mismatch | DEMEditorScene.tsx:210 | Align to HILLSHADE_PAINT_DEFAULTS | 2 | S |
| B-031 | P2 | LOW | duplicate copies visible:true | builder-layer-mutations.ts:84 | `layer.visible ?? true` | 1 | S |
| B-032 | P2 | LOW | ActiveFilterChips mislabels contains | ActiveFilterChips.tsx:54-71 | Detect `["in",val,["get",f]]` first | 3 | S |
| B-033 | P2 | LOW | StackRow hasLabels hides symbol badge | StackRow.tsx:144 | Drop `&& renderMode!=='symbol'` | 4 | S |
| B-034 | P2 | LOW | hex input not debounced | StyleColorPicker.tsx:48-51 | Reuse 100ms debounce | 8 | S |
| B-035 | P2 | LOW | opacity slider re-renders editor at 60fps | LayerStyleEditor.tsx:177-196 | Extract memo'd OpacitySlider leaf | 8 | M |
| B-036 | P2 | LOW | LayerEditorPanel eager import | MapBuilderPage.tsx:53 | Lazy-load editor flyout | 8 | S |
| B-037 | P2 | LOW | MapUpdate lacks extra="forbid" | schemas.py:630 | Add ConfigDict(extra="forbid") | 9 | S |
| B-038 | P2 | LOW | sample_values unsanitized in prompt | chat_service.py:217-225 | Sanitize sample values | 6 | S |
| B-039 | P2 | LOW | non-admin AI perpetual spinner | use-ai-availability.ts:39 | Non-admin status path | 6 | M |
| B-040 | P2 | LOW | misc UX/token polish (LS-01/02, KB-02/03, BP-01/02, MS-01/02, MT-01, ES-01, DT-03/05/06/07, CP-01, EH-01/02) | various | per-finding fixes above | 7/9 | M |

Sorted: P0 (0) → P1 (B-001..B-017) → P2 (B-018..B-040).

---

## 11. Tested Flows and Skipped Areas

- **Static/code review:** all 9 dimensions, full-file reads. CRITICAL/HIGH findings orchestrator-confirmed by direct read.
- **Existing unit tests observed:** broad builder vitest coverage exists (`__tests__/` ~70 files incl. `use-builder-layers.*`, `map-sync.*`, `LayerFilterEditor`, `color-relief-sync`, `BasemapPicker`, a11y). Note: `use-filtered-feature-count` and visibility-toggle tests mask B-003/B-004 with permissive mocks/fixtures — regression tests should assert the `layer-${id}` prefix.
- **Skipped (this pass):** live Playwright MCP visual verification (§7 list) and the e2e/pytest gates — reserved for the remediation verification pass with the live stack.

## 12. Builder Health Summary

- **Total findings:** 1 CRITICAL, 2 HIGH, ~18 MEDIUM, ~30 LOW/INFO.
- **By dimension:** Chat 10 (1C/1H), Layer 9, Style 8, UX 20+, Perf 11, Conventions 14 (all low/info), Share 8, Label 7, Filter 3.
- **P0:** 0 (no data loss, no security/edition bypass). **P1:** 17. Estimated P0+P1 effort: ~2–3 focused days (mostly S/M).
- **Top 3 recommendations:**
  1. Fix the chat `ChatAction` schema (B-001 rows/columns, B-002 dataset_name) — small change, restores a visibly-broken feature.
  2. Close the `-arrow` companion gaps (B-004/B-005/B-006) and the filter-count layer-id bug (B-003) — one-line fixes, real user-visible correctness.
  3. Symbol/heatmap label guards (B-008/B-009) and AdvancedJsonEditor `_`-key handling (B-010/B-011) — prevent flicker/validation dead-ends.

## 13. Comparison to Prior Audit (builder-audit-20260528.md, 2 days prior)

A full file-level diff against `builder-audit-20260528.md` was not machine-computed in this pass (the prior report predates the active plugin-rename refactor, which moved several maps/service files). Qualitative diff:

- **NEW (introduced or first-surfaced here):** B-001/B-002 chat `ChatAction` field gaps (high-confidence, confirmed); B-003 filter-count layer-id bug; the `-arrow` companion cluster (B-004/B-005/B-006).
- **PERSISTENT (long-standing architectural, expected):** fixed-width sidebar (LA-01), `styleDiffing={false}` (ME-02), PNG-export light colors (IF-02), basemap eye disabled (BP-02) — all intentional/documented.
- **RESOLVED since prior cycles:** edition gating + token scoping + CSP/sandbox now verify clean (no CRITICAL/HIGH in Share/Embed) — a strengthening vs earlier security-flagged cycles.

A precise NEW/RESOLVED/REGRESSED/PERSISTENT match table should be regenerated once the plugin-rename milestone settles file paths.
