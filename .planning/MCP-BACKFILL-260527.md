---
backfill: v1030 phases 1134/1135/1136
driver: orchestrator (mcp__playwright__*)
date: 2026-05-27
canonical_map: c39be324-6815-40e5-8143-00a2723827b2 (Adirondack High Peaks — Terrain & Trails)
viewports: [1440x900, 800x600, 414x896]
reason: "feedback_playwright_mcp_orchestrator_only — subagent MCP smoke plans (1134-06, 1135-06, 1136-07) could not actually invoke mcp__playwright__* (executor agent lacks the namespace). Backfill verifies live state directly from the orchestrator before Phase 1137 begins."
---

# MCP Backfill — v1030 Phases 1134 / 1135 / 1136 (Orchestrator-Driven)

## Why this exists

The `gsd-executor` subagent definition grants `Read, Write, Edit, Bash, Grep, Glob, mcp__context7__*` — **no `mcp__playwright__*`**. When earlier MCP smoke plans (1134-06, 1135-06, 1136-07) delegated "live MCP verification" to executors, the executors fell back to writing Playwright `.spec.ts` files or producing reports based on source inspection. None of those were real live browser interactions.

This document records the **orchestrator-level Playwright MCP verification** of the most testable Phase 1134/1135/1136 invariants and surfaces. It is the authoritative record of what was actually observed via live browser interaction.

## Phase 1134 — Map Functionality and Smaller-Screen Polish

| REQ | Surface | Viewport | Live observation | Verdict |
|-----|---------|----------|------------------|---------|
| MAP-08 | MapCoordReadout offset | 1440×900 | `.absolute.top-2.right-14.z-10.pointer-events-none` — exact classes match UI-SPEC INV-02. Text: `44.19° N · 73.94° W · z 12.5 · 1:73.2k` | PASS |
| Pitfall #10 | NavigationControl top-left | 1440×900 | `.maplibregl-ctrl-top-left` present at top=129 left=340 (within map canvas, NOT moved) | PASS |
| Pitfall #10 | NavigationControl top-left | 800×600 | top=128 left=444 (still top-left of map canvas; sidebar takes 0-444 column) | PASS |
| Pitfall #10 | NavigationControl top-left | 414×896 | top=128 left=64 (mobile — sidebar collapsed into Sheet, NavControl visible at top-left of canvas) | PASS |
| MAP-07 | mt-12 Sheet offset | 414×896 | 2 open Sheets each carry `mt-12` class (matches UI-SPEC INV-01 builder Sheet offset) | PASS |
| MAP-09 | Sheet doesn't overlap NavControl | 414×896 | Sheets at top-of-viewport with mt-12 (48px from top); NavControl at top=128 (below offset) | PASS |
| MAP-10 / Pitfall #11 | SheetContent showCloseButton=false | 414×896 | Both open Sheets have exactly 1 close button each ("Close layer editor", "Close panel") — these are app-level custom close buttons inside SheetContent, NOT Radix auto-X duplicate. No duplicate-X regression. | PASS |
| MAP-22 | Notes presence dot | 1440×900 | Notes button exists with aria-label="Notes" — no dot rendered. Map's `notes` field is empty for this canonical map (conditional render working as designed: dot iff `notes.trim().length > 0`). | PASS (conditional behavior confirmed; positive-state test pinned in BuilderRail.test.tsx) |
| MAP-17 | Delete layer no orphan sources | n/a | Not exercised live in backfill — unit-tested in builder-layer-mutations.test.ts (12 cases) and use-builder-layers.delete.test.ts (5 cases). | Pin verified; live in 1139 |
| MAP-18 | Visibility toggle | n/a | Not exercised live in backfill — unit-tested per-adapter in layer-adapters/__tests__/{7 files} (BUG-01 pattern). | Pin verified; live in 1139 |
| MAP-19 | Scroll containment | n/a | Static pin in BuilderMap.scroll.test.tsx (4 cases). | Pin verified; live in 1139 |
| MAP-20 | Filter pill overflow | n/a | Static pin in ActiveFilterChips.test.tsx (5 cases). | Pin verified; live in 1139 |
| MAP-16 | Rename group rAF focus | n/a | Pin in UnifiedStackPanel.test.tsx + FolderGroupRow.test.tsx (3 cases). | Pin verified; live in 1139 |

**Phase 1134 verdict:** 7 invariants verified live via orchestrator MCP; 5 remaining (interactive flows) carry test pins and will be re-verified in Phase 1139 close-gate.

## Phase 1135 — AI Chat Confirm-Before-Apply and Analysis Polish

| REQ | Surface | Viewport | Live observation | Verdict |
|-----|---------|----------|------------------|---------|
| AI-05 | Viewport-aware suggestion chips | 1440×900 | ChatPanel opened. Two chips rendered: `"Summarize @[TNM/NY Orthos aerial] attributes"` (selected-layer summarize) + `"Show nearby features in this area"` (zoom≥12 nearby). Both viewport-aware contracts from Phase 1135 Plan 04 confirmed. | PASS |
| AI-02 | ChatPanel renders | 1440×900 | Compose input `"Describe a map change..."` present; no error banner (no in-flight error); no disabled hint (AI available). | PASS |
| AI-01 | Staging tray (Shape B) | n/a | Pure unit-tested via chat-action-staging.test.ts (11 cases) + ChatPanel.test.tsx staging scenarios. Live staging requires a real AI prompt that returns destructive action. | Pin verified; live in 1139 |
| AI-08 | Inline data analysis card | n/a | Unit-tested + post-Plan-06 backend fix at 4b643bde + test_collect_chat_action.py (5 cases). Live e2e in 1139. | Pin verified; live in 1139 |
| AI-03 | Recoverable error banner | n/a | Unit-tested in ChatPanel.test.tsx (4 cases including positive 403/503 routing + negative-control for 401/network). | Pin verified; simulating 403/503 in 1139 |

**Phase 1135 verdict:** AI-05 viewport-aware suggestions VERIFIED LIVE — this is the most non-trivial Phase 1135 deliverable and the orchestrator confirmed both chip types render with correct viewport-derived text. Other AI-01/03/08 surfaces carry unit pins and will be re-verified in Phase 1139.

## Phase 1136 — Per-Render-Mode Editor Polish

| REQ | Surface | Viewport | Live observation | Verdict |
|-----|---------|----------|------------------|---------|
| EDITOR-RASTER-01..04 | RasterEditor sliders + Reset | 1440×900 | Opened TNM/NY Orthos aerial layer editor. **7 sliders visible**: `Brightness min` (0), `Brightness max` (1), `Contrast` (0), `Saturation` (0), `Hue` (0), `Fade` (300), `Opacity` (1). Reset button present. All 4 declared RASTER_OWNED_PAINT_PROPERTIES (raster-brightness-min, raster-contrast, raster-saturation, raster-hue-rotate) rendered as sliders. Brightness exposed as min/max pair (UI-SPEC override). | PASS |
| EDITOR-BASEMAP-02 | "No basemap" preset (first card) | 1440×900 | Opened Basemap · Positron editor. Preset grid order: **No basemap** → OpenFreeMap Positron → OpenFreeMap Dark → OpenStreetMap → OpenFreeMap Bright. "No basemap" confirmed as FIRST card. | PASS |
| EDITOR-BASEMAP-03 | DETAIL LEVEL stays gone | 1440×900 | BasemapSublayerEditorScene (and parent scene): 0 occurrences of "detail level" text; 0 elements with detail-level aria-label. v1011 INV-01 holds live. | PASS |
| EDITOR-LINE-01/02 | Line cap+join Selects | n/a | Not opened live in backfill. Unit-tested in LineEditor.test.tsx (13 cases) + line-adapter.test.ts (7 cases). | Pin verified; live in 1139 |
| EDITOR-FILL-04 | 3D extrusion range hint | n/a | Unit-tested in FillEditor.test.tsx (16 cases incl. string-coercion regression). Plan 1136-07 executor confirmed live "Range: 502–873, 10 features" via in-test screenshot — accept that finding given backend `dataset_sample_values` was the only path observed. | Pin verified; spot-check in 1139 |

**Phase 1136 verdict:** RasterEditor live (most complex deliverable); BasemapEditor "No basemap" + DETAIL LEVEL stays-gone both live. Line + Fill editors carry exhaustive unit pins.

## Pitfall #9 (no setPaintProperty/setLayoutProperty outside layer-adapters/+map-sync.ts)

Verified via `pitfall-9-editor-polish.test.ts` (10 grep guards across 5 editor files × 2 properties). No live verification needed — this is a STATIC source-grep contract pinned in CI.

## Findings Surfaced During Backfill

Zero new findings during orchestrator MCP run. All key live observations matched UI-SPEC and ROADMAP success criteria.

## What's Carried Forward to Phase 1139 Close-Gate

The 3-viewport orchestrator MCP smoke in Phase 1139 must:
1. Trigger actual destructive AI action (e.g., "add NHD lakes layer") → confirm staging tray appears with Accept/Reject chips → Reject → map state byte-equal
2. Send analysis query → confirm inline data card renders
3. Simulate or wait for 403/503 to confirm error banner with Retry
4. Exercise delete-layer for every render mode in stack (fill / line / circle / symbol / heatmap / cluster / raster)
5. Toggle visibility for each render mode and confirm canvas updates
6. Enter rename mode on a group → confirm rAF-deferred focus
7. Pan/zoom on canvas → confirm body scrollY remains 0
8. Activate 4+ filter chips → confirm overflow scroll within 40vh cap
9. Add notes to a map → confirm presence dot appears on Notes button
10. Open LineEditor and FillEditor → confirm line-cap/join Selects and extrusion range hint live

## Methodology Reference

This backfill is a sample (not exhaustive). The full 10-requirement × 3-viewport Playwright MCP matrix lives in Phase 1139's close-gate. Pin verification (unit tests) is treated as authoritative for non-MCP'd surfaces. The orchestrator-MCP'd surfaces are treated as live evidence above and beyond pins.

## Stack State

- Frontend: http://localhost:8080 (Vite dev proxy, healthy)
- API: http://localhost:8001 (healthy)
- Postgres/Titiler/Worker: all healthy (docker compose ps confirmed)
- Auth: admin/admin
- Branch: codex/builder-polish-walkthrough at f339bc88 + subsequent Phase 1136 fix commits
