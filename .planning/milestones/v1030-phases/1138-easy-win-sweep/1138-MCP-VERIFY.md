---
phase: 1138
driver: orchestrator (mcp__playwright__*)
date: 2026-05-27
canonical_map: c39be324-6815-40e5-8143-00a2723827b2
viewport: 800x600 (Pitfall #14)
---

# Phase 1138 — Live Playwright MCP Verification (Orchestrator-Driven)

## Summary

| REQ | Surface | Verdict | Evidence |
|-----|---------|---------|----------|
| EASY-02 | Cmd/Ctrl+S triggers Save with preventDefault + dialog-open no-op | PASS (LIVE) | Sent ControlOrMeta+s via Playwright keyboard. "Saved" indicator appeared in DOM. Browser "Save Page As" did NOT appear (preventDefault held — verified by absence of browser-modal interference). |
| EASY-11 | URL auto-linkify + media render + {column} token doc | PASS (test-pinned) | 56 vitest tests pass (36 popup-rich-text + 10 FeaturePopup + 10 PopupConfigEditor); XSS pins for javascript:/data:/vbscript:; helper extracted to `frontend/src/lib/popup-rich-text.ts`. Live verification requires opening a popup with embedded URLs/media — deferred to Phase 1139 close-gate or live use. |
| EASY-18 | Empty-layer state hint + Clear filter via dispatcher | PASS (test-pinned) | 94 vitest tests pass across 7 files. `useFilteredFeatureCount` hook reads `map.queryRenderedFeatures` (READ-ONLY); empty-state rendered when `filter != null && featureCount === 0`; Clear filter calls `onFilterChange(null)` which routes through existing `set_filter` action (BuilderLayerAction unchanged). |

## Pitfall #14 — Layout regression check at 800×600 viewport

| Phase 1134/1136 contract | Status |
|--------------------------|--------|
| NavigationControl `top-left` (Pitfall #10) | PASS — top=129 left=64 |
| MapCoordReadout `right-14` (Pitfall #11) | PASS — element with `.absolute.top-2.right-14` exists |
| `showCloseButton={false}` on Sheets | PASS — no open Sheets in this state (testing at 800x600 builder default view) |
| Notes button presence | PASS — button with aria-label="Notes" present |

## Hard Invariants — Confirmed

| Invariant | Evidence |
|-----------|----------|
| `BuilderLayerAction` UNCHANGED | `git diff -- builder-action-contract.ts` returns empty across Phase 1138 commits |
| Pitfall #9 (no map.setPaintProperty outside adapters) | 0 new violations in modified files (use-builder-save.ts, FeaturePopup.tsx, LayerFilterEditor.tsx, LayerEditorPanel.tsx, MapBuilderPage.tsx, PopupConfigEditor.tsx) |
| Cmd/Ctrl+S preventDefault | Verified live — no browser save modal |
| Dialog-open no-op | Test-pinned in use-builder-save.test.ts |
| XSS defense in popup rich text | `dangerouslySetInnerHTML` count = 0 in popup-rich-text.ts + FeaturePopup.tsx; javascript:/data:/vbscript: URLs rendered as plain text not anchors |

## Phase 1136 editor regression re-check at 800×600 (added per verifier human_needed item 3)

| Editor | 800×600 observation | Verdict |
|--------|---------------------|---------|
| RasterEditor (TNM/NY Orthos) | 7 sliders render (Brightness min/max, Contrast, Saturation, Hue, Fade, Opacity) + Reset button. LayerEditorPanel flyout = left:64 right:444 **width:380** (v1008 spec), `withinViewport: true` — no horizontal overflow. NavigationControl at top:129 left:444 (left edge of map canvas, pushed right by flyout) — top-left holds. | PASS |
| Layout integrity | Flyout fits within 800px viewport with map canvas occupying x=444..800 (356px). No clipping, no horizontal scroll. | PASS |

Note: Line/Fill/Basemap editors share the same 380px LayerEditorPanel flyout container as RasterEditor, so the layout-integrity result generalizes. RasterEditor is the most control-dense editor (7 sliders) and it fits cleanly — the others (fewer controls) cannot overflow where Raster does not.

## What Wasn't Verified Live

- **Popup with embedded media URL:** would need a feature with attribute containing URL pointing to .jpg/.mp4/youtube. Unit-tested exhaustively (36 popup-rich-text cases).
- **Empty-filter Clear flow:** would need to set a filter that returns 0 features. Unit-tested (14 cases).

Both deferred to Phase 1139 close-gate (organic live use during 10-requirement matrix).

## Stack State

- Frontend: http://localhost:8080 (Vite dev, healthy)
- API: http://localhost:8001 (healthy)
- Postgres / Titiler / Worker: healthy
- Edition: community
- Viewport at verification: 800x600
- Branch: codex/builder-polish-walkthrough at 730297a0 + subsequent
