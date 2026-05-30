---
slug: builder-qa-smoke
status: complete
date: 2026-05-30
type: qa-smoke
code_changes: false
---

# SUMMARY — Map Builder QA Smoke Pass

Live Playwright-MCP QA sweep across all 4 current maps (raster, vector+DEM marketing,
9-layer 3D terrain, empty). Orchestrator-driven (subagents lack MCP access).

## Outcome

Builder is functionally healthy. No code changes made (this was an evaluation pass).

- **F1 (blocker symptom, resolved):** raster colormap/stretch reverted to grayscale on
  reload — traced to a **stale Vite bundle** (21h-old frontend container predated today's
  fix `de9d1f8d`), NOT a code defect. Fixed by `docker compose restart frontend`; round-trip
  then verified end-to-end.
- **F2 (minor):** Settings widget toggles (e.g. Measure) don't set the dirty flag — save
  button stays "Saved", no nav-guard; data still persists on explicit Cmd+S. Root cause:
  `useWidgetStore.toggle` (`MapBuilderPage.tsx:331`) never calls `setHasUnsavedChanges`.
- **F3 (info):** Projection (Mercator/Globe) is runtime-only by design; reverts on reload,
  no persistence cue.
- **All round-trips pass:** raster colormap/stretch, vector fill-opacity, layer visibility
  (correctly marks dirty), widgets (on explicit save). Save = PATCH/PUT 200, no 422s. Zero
  console errors on all 4 maps (excepting an expected mid-session JWT-expiry burst).

See `FINDINGS.md` for detail + `screenshots/` for evidence.

## Follow-ups (optional, not done here)

- Fix F2: wire `setHasUnsavedChanges(true)` into the widget-toggle path.
- Consider F3: persist projection or add a "not saved" affordance.
