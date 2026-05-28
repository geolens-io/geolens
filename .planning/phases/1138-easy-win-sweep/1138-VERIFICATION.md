---
phase: 1138-easy-win-sweep
verified: 2026-05-28T00:00:00Z
status: passed
close_gate_resolution: "human_needed items deferred to Phase 1139 close-gate; verified live in 1139-CLOSE-GATE-SMOKE.md (3-viewport MCP + disabled-AI + save-persist + shared/embed parity). See v1030-MILESTONE-AUDIT.md."
score: 3/4 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Live Playwright MCP at 800px viewport verifies all three easy-wins (EASY-11 popup URL/media + EASY-18 empty-state hint) do not regress any Phase 1134/1136 layout fix"
    addressed_in: "Phase 1139"
    evidence: "Phase 1139 SC#1: 'Live Playwright MCP smoke at 800×600 ... every render mode renders, layer ops work, save persists across reload'; MCP-VERIFY.md explicitly records 'Both deferred to Phase 1139 close-gate (organic live use during 10-requirement matrix)'"
human_verification:
  - test: "Verify EASY-11 popup URL/media rendering live at 800x600"
    expected: "Open a feature popup on a layer with a URL-valued property; URL renders as clickable anchor; image URL renders as <img loading=lazy>; YouTube URL renders as iframe with sandbox; embedded text URLs auto-linkify"
    why_human: "Requires live map session with a dataset that has a URL-valued property column. No such column exists on the canonical ADK map; vitest confirms the rendering contract (36+10+10 = 56 tests) but live browser verification of URL → <img>/<video>/<iframe> rendering requires a real feature click."
  - test: "Verify EASY-18 empty-state hint visible and Clear filter works live at 800x600"
    expected: "Apply a filter that eliminates all features (e.g., name='ZZZZ_DOES_NOT_EXIST_ZZZZ'); the Filter tab shows '0 features — check your filter' hint with a Clear filter button; clicking Clear filter removes the hint and restores features"
    why_human: "Requires live map interaction: add a filter, wait for map idle, observe the hint. The queryRenderedFeatures hook only fires after map idle; automated tests mock this. This is the one live surface that tests cannot substitute for."
  - test: "Verify Phase 1136 editor items do not regress at 800x600 (Pitfall #14 completion)"
    expected: "RasterEditor 4 sliders + Reset visible and not clipped; LineEditor cap/join Selects accessible; FillEditor extrusion range hint visible for a 3D layer; BasemapEditor No-basemap preset card visible"
    why_human: "MCP-VERIFY.md Pitfall #14 table covered only Phase 1134 layout items (NavigationControl, CoordReadout, SheetContent, Notes). Phase 1136 editor-specific items were not verified in the 1138-MCP-VERIFY.md session. Plan 04 checklist Section 4 items 4-7 were documented as required but not recorded as executed."
---

# Phase 1138: Easy-Win Sweep — Verification Report

**Phase Goal:** Close the cross-cutting easy-win items that don't fit any single bucket (keyboard shortcut, popup affordances, empty-layer state). Catches the long tail without forcing items into a previous phase.
**Verified:** 2026-05-28
**Status:** human_needed — 3/4 truths VERIFIED, SC#4 PARTIAL (EASY-02 live PASS, EASY-11/EASY-18 test-pinned, Phase 1136 regression at 800px unrecorded; all three items deferred to Phase 1139 close-gate)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Cmd/Ctrl+S triggers Save when builder focused; no-op when dialog open; preventDefault; visible toast on success | VERIFIED | `use-builder-save.ts:730` unconditionally calls `e.preventDefault()`; `document.querySelector('[role="dialog"][data-state="open"]')` gate at line 737-738; `useBuilderSave()` invoked from `MapBuilderPage.tsx:256`; 6 EASY-02 tests (including 5 new pins) all pass; MCP-VERIFY.md records PASS (LIVE) at 800x600 |
| 2 | PopupConfigEditor + popup renderer detect URLs (auto-linkify) and basic media (.jpg/.png/.mp4 + YouTube); {column} token syntax documented | VERIFIED | `popup-rich-text.ts` exports `detectUrls`, `classifyUrl`, `normalizeYouTubeEmbed`, `splitTextWithUrls`; `FeaturePopup.tsx` imports and uses `splitTextWithUrls`+`classifyUrl` (lines 9, 262, 333); image/video/youtube/other branches all implemented with `max-h-32`, `loading="lazy"`, YouTube iframe sandbox; `PopupConfigEditor.tsx:226` renders `t('popup.mediaHint')`; all 4 locales have `mediaHint`; 56 total tests pass (36+10+10); `dangerouslySetInnerHTML` count = 0 |
| 3 | When a layer renders zero features (filter active), LayerEditorPanel shows "0 features — check your filter" hint + Clear filter button dispatching through BuilderLayerAction (no bypass) | VERIFIED | `use-filtered-feature-count.ts` uses read-only `map.queryRenderedFeatures` with idle-debounce and null-safety; `LayerFilterEditor.tsx:458` has `showEmptyState = filter != null && featureCount === 0`; `onFilterChange(null)` call at line 483; `LayerEditorPanel.tsx:531` forwards `featureCount` to `LayerFilterEditor`; `MapBuilderPage.tsx` invokes hook at line 436, passes `filteredFeatureCount` at lines 1301 and 1352; `emptyResult.{title,help,clear}` in all 4 locales; 14 EASY-18 tests pass (7+5+2); `dispatchLayerAction` NOT called from LayerFilterEditor; Pitfall #9 grep returns 0; `builder-action-contract.ts` diff = 0 lines |
| 4 | Live Playwright MCP at 800px viewport verifies all three easy-wins do not regress any Phase 1134/1136 layout fix | PARTIAL | MCP-VERIFY.md (commit `bf463ff6`) records EASY-02 PASS (LIVE) at 800x600 and Phase 1134 layout holds (NavigationControl top=129/left=64; CoordReadout right-14; SheetContent; Notes). EASY-11 and EASY-18 recorded as "test-pinned, deferred to Phase 1139 close-gate". Phase 1136 editor items (RasterEditor sliders, LineEditor cap/join, FillEditor extrusion hint, BasemapEditor No-basemap) NOT recorded in the 800px session. `1138-MCP-SMOKE.md` (Plan 04 required artifact) was not created; `1138-04-SUMMARY.md` is missing. |

**Score:** 3/4 truths verified (SC#1 VERIFIED, SC#2 VERIFIED, SC#3 VERIFIED, SC#4 PARTIAL)

### Deferred Items

Items not yet fully met but explicitly addressed in a later milestone phase.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | EASY-11 live popup URL/media verification at 800px | Phase 1139 | MCP-VERIFY.md: "Live verification requires opening a popup with embedded URLs/media — deferred to Phase 1139 close-gate or live use." Phase 1139 SC#1: "every render mode renders" at 800×600 |
| 2 | EASY-18 live empty-state hint + Clear filter verification at 800px | Phase 1139 | MCP-VERIFY.md: "deferred to Phase 1139 close-gate (organic live use during 10-requirement matrix)." Phase 1139 SC#1 covers "layer ops ... work" at 800×600 |
| 3 | Phase 1136 editor regression check at 800px (RasterEditor, LineEditor, FillEditor, BasemapEditor) | Phase 1139 | Phase 1139 SC#1: "every render mode renders" covers all editor types at 800×600 |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/builder/hooks/use-builder-save.ts` | Cmd/Ctrl+S listener with dialog-open gate + unconditional preventDefault | VERIFIED | Lines 725-745: preventDefault moved above isPending guard; `document.querySelector('[role="dialog"][data-state="open"]')` gate at line 737 |
| `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` | 5+ EASY-02 regression tests | VERIFIED | 6 EASY-02 occurrences; 5 new test cases in `describe('EASY-02: Cmd/Ctrl+S keyboard shortcut gating')` block (lines 894-982); file is 1680 lines |
| `frontend/src/lib/popup-rich-text.ts` | Pure helpers: detectUrls, classifyUrl, normalizeYouTubeEmbed, splitTextWithUrls | VERIFIED | 113 lines; all 4 functions exported; XSS-gated http/https-only regex; no React imports, no DOM access; `dangerouslySetInnerHTML` = 0 real lines (1 docstring comment only) |
| `frontend/src/lib/__tests__/popup-rich-text.test.ts` | URL detection, media classification, YouTube extraction, XSS pins (100+ lines) | VERIFIED | 225 lines; 36 EASY-11 test cases including javascript:/data:/vbscript: XSS rejection pins |
| `frontend/src/components/map/FeaturePopup.tsx` | New media rendering branches using popup-rich-text | VERIFIED | Imports `splitTextWithUrls`, `classifyUrl` at line 9; image branch at line 264; video at line 288; YouTube at line 301; inline URL linkification at line 330; `loading="lazy"` on img and iframe; `dangerouslySetInnerHTML` = 0 |
| `frontend/src/components/builder/PopupConfigEditor.tsx` | mediaHint paragraph with t('popup.mediaHint') | VERIFIED | Line 226: `{t('popup.mediaHint')}` inside Visible Fields div |
| `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` | popup.mediaHint key in all 4 locales | VERIFIED | All 4 locales have `"mediaHint"` at line 375 with translations |
| `frontend/src/components/builder/hooks/use-filtered-feature-count.ts` | Hook returning rendered-feature count via queryRenderedFeatures + idle-debounce | VERIFIED | 72 lines; `map.queryRenderedFeatures` at line 51; `map.off('idle', handleIdle)` cleanup; null-safety for map/layer/filter/getLayer checks; READ-ONLY docstring |
| `frontend/src/components/builder/hooks/__tests__/use-filtered-feature-count.test.ts` | 7+ EASY-18 null-safety tests (100+ lines) | VERIFIED | 160 lines; 7 EASY-18 occurrences |
| `frontend/src/components/builder/LayerFilterEditor.tsx` | featureCount prop + showEmptyState block + Clear button | VERIFIED | Lines 28, 458, 470-485: `featureCount?: number | null`; `showEmptyState = filter != null && featureCount === 0`; `onClick={() => onFilterChange(null)}`; `t('layerEditor.emptyResult.title')` etc. |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | featureCount prop forwarded to LayerFilterEditor | VERIFIED | Lines 69, 159, 531: prop declared, destructured, forwarded with `featureCount={featureCount ?? null}` |
| `frontend/src/pages/MapBuilderPage.tsx` | useFilteredFeatureCount invoked; featureCount on both LayerEditorPanel mount sites | VERIFIED | Line 78 import; line 436 invocation; lines 1301 and 1352: `featureCount={filteredFeatureCount}` |
| `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` | layerEditor.emptyResult.{title,help,clear} in all 4 locales | VERIFIED | All 4 locales have `"emptyResult"` block at line 1021 with title/help/clear translations |
| `.planning/phases/1138-easy-win-sweep/1138-MCP-SMOKE.md` | Orchestrator-driven smoke checklist (Plan 04 artifact) | MISSING | File does not exist. Orchestrator created `1138-MCP-VERIFY.md` instead, which is a results record, not the checklist artifact. Plan 04 remains marked `[ ]` in ROADMAP. |
| `.planning/phases/1138-easy-win-sweep/1138-04-SUMMARY.md` | Plan 04 completion summary | MISSING | File does not exist. Plan 04 task 2 (hand-off to orchestrator) was not completed with a summary file. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `frontend/src/pages/MapBuilderPage.tsx` | `use-builder-save.ts` | `useBuilderSave()` invocation | WIRED | Line 256: `useBuilderSave({...})` — route-gates the keyboard listener by hook lifecycle |
| `use-builder-save.ts` | DOM `[role="dialog"][data-state="open"]` | `document.querySelector` in keydown handler | WIRED | Line 737: `const dialogOpen = document.querySelector('[role="dialog"][data-state="open"]');` |
| `FeaturePopup.tsx` | `popup-rich-text.ts` | `import { splitTextWithUrls, classifyUrl }` | WIRED | Line 9; both functions used in ValueDisplay body |
| `PopupConfigEditor.tsx` | `builder.json popup.mediaHint` | `t('popup.mediaHint')` | WIRED | Line 226; key exists in all 4 locales |
| `LayerFilterEditor.tsx` | `onFilterChange(null)` | Clear filter button onClick | WIRED | Line 483: `onClick={() => onFilterChange(null)}` — NOT calling dispatchLayerAction directly |
| `MapBuilderPage.tsx` | `dispatchLayerAction { type: 'set_filter' }` | `layerEditorHandlers.onFilterChange` at line 347-348 | WIRED | `onFilterChange(layerId, expression)` dispatches `{ type: 'set_filter', source: 'manual', layerId, expression }` |
| `MapBuilderPage.tsx` | `use-filtered-feature-count.ts` | `useFilteredFeatureCount(mapInstance, editingLayer ?? null)` | WIRED | Line 436 invocation; result passed to both LayerEditorPanel sites (lines 1301, 1352) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `FeaturePopup.tsx` ValueDisplay | `value` (feature property value) | `feature.properties` from real MapLibre queryRenderedFeatures results | Yes — real feature data from tile requests | FLOWING |
| `LayerFilterEditor.tsx` empty-state | `featureCount` | `useFilteredFeatureCount` → `map.queryRenderedFeatures` (real MapLibre API) | Yes — real rendered feature count | FLOWING |
| `PopupConfigEditor.tsx` mediaHint | static i18n string via `t('popup.mediaHint')` | locale JSON | Yes — locale string rendered | FLOWING |

### Behavioral Spot-Checks

Step 7b: SKIPPED — requires a running dev server with the Playwright MCP. The `frontend/` changes are all React components and hooks; the application cannot be meaningfully exercised without a live browser session.

### Probe Execution

No probes defined for this phase. SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| EASY-02 | 1138-01 | Cmd/Ctrl+S triggers map Save when builder focused; no-op when dialog/modal open; visible toast | SATISFIED | Implementation verified in code + test + live MCP (EASY-02 PASS) |
| EASY-11 | 1138-02 | PopupConfigEditor + popup renderer support URLs (auto-linkify) and basic media | SATISFIED | popup-rich-text.ts + FeaturePopup wiring + PopupConfigEditor mediaHint verified; 56 tests pass; live popup session deferred to Phase 1139 |
| EASY-18 | 1138-03 | LayerEditorPanel surfaces "0 features" hint + clear filter button when layer renders zero features | SATISFIED | useFilteredFeatureCount + LayerFilterEditor + LayerEditorPanel + MapBuilderPage wiring verified; 14 tests pass; live session deferred to Phase 1139 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `LayerFilterEditor.tsx` | 579, 599, 628 | `placeholder=` attribute on `<SelectValue>` / `<Input>` | Info | UI Select/Input placeholder strings — legitimate shadcn usage, not stub code |
| `use-builder-save.ts` | 430 | `// so the frontend is the primary UX gate for placeholder correctness` | Info | Comment about placeholder template syntax, not a stub indicator |

No TBD/FIXME/XXX markers found in any Phase 1138 modified files. No `dangerouslySetInnerHTML` in production code (only in a docstring comment in popup-rich-text.ts). No hardcoded empty arrays flowing to rendering. `BuilderLayerAction`/`BuilderActionSource` unchanged (0 lines diff on `builder-action-contract.ts`). Pitfall #9 grep returns 0 across all 7 Phase 1138 modified files.

### Human Verification Required

#### 1. EASY-11 Popup URL/Media — Live Verification at 800x600

**Test:** At 800x600 viewport, navigate to a builder map that has at least one layer with a URL-valued property (e.g., a `wiki_url` or `photo_url` column). Click a feature to open the popup. Verify:
- A property containing a plain URL renders as a clickable `<a>` anchor
- A property containing an `.jpg` or `.png` URL renders an `<img loading="lazy">` with a fallback anchor below
- A property containing a YouTube URL renders an `<iframe sandbox="allow-scripts allow-same-origin allow-presentation">`
- A property value containing "See https://example.com for details" (URL embedded in text) renders the URL portion as an anchor while surrounding text remains as text

**Expected:** All four cases render as described. No `<a href="javascript:...">` anchor exists in the DOM (`document.querySelectorAll('a[href^="javascript:"]').length === 0`).

**Why human:** Requires a dataset with a URL-valued property column. The canonical ADK map does not have one. Vitest covers the rendering contract exhaustively (56 tests), but live browser rendering with real HTML element inspection confirms the wire is end-to-end.

---

#### 2. EASY-18 Empty-State Hint — Live Verification at 800x600

**Test:** At 800x600 viewport, open the builder on a map with a filterable vector layer. Open the Filter tab. Add a filter condition guaranteed to return 0 features (e.g., `name = 'ZZZZ_DOES_NOT_EXIST_ZZZZ'`). Wait approximately 1-2 seconds for map idle. Verify:
- A `role="status"` block appears in the Filter tab with the text "0 features — check your filter"
- A "Clear filter" button is visible within the block
- Clicking "Clear filter" removes the hint, clears the filter conditions, and causes the ActiveFilterChips (above the map canvas) to update

**Expected:** Hint appears after map idle with 0 rendered features; Clear button routes through the existing dispatcher (no map.setFilter call from the editor side); hint disappears after clear.

**Why human:** The `useFilteredFeatureCount` hook fires after `map.idle` events, which only occur in a live browser with a real MapLibre instance. Vitest mocks the idle subscription; the real-world firing sequence and 250ms debounce behavior require a live session.

---

#### 3. Phase 1136 Editor Regression at 800x600 (Pitfall #14 Completion)

**Test:** At 800x600 viewport, open each editor type on the canonical ADK map:
- **RasterEditor:** Click a raster/DEM layer; open its style editor; confirm brightness, contrast, saturation, hue-rotate sliders are visible (not clipped by the 800px layout) and a Reset button exists
- **LineEditor:** Click a line layer; open its style editor; confirm line-cap (butt/round/square) and line-join (bevel/round/miter) Selects are visible and clickable
- **FillEditor:** If a 3D extrusion fill layer exists, open its editor; confirm "Range: X–Y, N features" hint is visible
- **BasemapEditor:** Open the basemap group editor; confirm "No basemap" preset card is visible; clicking it sets a transparent background

**Expected:** All 4 editor items render correctly and are not clipped or overlapping other elements at 800px. Phase 1136 regression items pass.

**Why human:** The 1138-MCP-VERIFY.md session only verified Phase 1134 layout items (4 items). Plan 04 section 4 required Phase 1136 items (4 more) but they were not recorded in the orchestrator's verification session. This is the gap in SC#4's "verifies all three easy-wins do not regress any Phase 1134/1136 layout fix."

---

### Gaps Summary

**SC#4 is PARTIAL** — the core gap is that Plan 04 was not completed as specified:

1. **1138-MCP-SMOKE.md** (Plan 04 Task 1 artifact) was never created. The orchestrator created `1138-MCP-VERIFY.md` instead (a results record, not the checklist). The ROADMAP correctly shows `1138-04-PLAN.md` as `[ ]` (incomplete).

2. **1138-04-SUMMARY.md** (Plan 04 Task 2 artifact) was never created.

3. **EASY-11 and EASY-18 live verification at 800px** was deferred. The MCP-VERIFY.md explicitly says these require a feature with a URL-valued property and an active filter that returns 0 features, which the canonical ADK map did not satisfy during the session.

4. **Phase 1136 editor regression at 800px** was not recorded in the 800px session (MCP-VERIFY.md only covers 4 Phase 1134 items).

**These are all human-verifiable items.** The implementation code (SC#1, SC#2, SC#3) is fully correct, substantive, and wired. The gap is exclusively in live browser confirmation of SC#4's Pitfall #14 requirement.

**Deferred disposition:** Items 3 and 4 above are explicitly deferred to Phase 1139 (close-gate), which runs live MCP at 800×600 across all render modes. The MCP-VERIFY.md records this deferral explicitly. Items 1 and 2 (missing artifacts) are human decisions: either create the artifacts retroactively or close Plan 04 with the existing MCP-VERIFY.md as sufficient evidence.

---

_Verified: 2026-05-28_
_Verifier: Claude (gsd-verifier)_
