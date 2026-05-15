# Requirements: v1009.1 Builder Smoke Polish

## Milestone

**v1009.1 Builder Smoke Polish** — close out the 17 non-B-01 findings from the 2026-05-15 Map Builder Playwright smoke check. B-01 (live-add maplibre sync) already shipped at commit `85738f1c`. Restore the v1009 shipped promises (multi-select bulk-ops + UI/UX polish sweep) that the smoke check showed were unmet, plus low-cost backend/a11y hygiene wins.

## Goal

Every finding in `.planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md` resolved or explicitly justified as closed-by-B-01. Single CTRL-01 batch gate. Tag `v1009.1`.

## Source of truth

- `.planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md` — full smoke-check report with severity, repro, evidence, impact, likely cause, and files-to-investigate for each finding
- 18 reproduction screenshots in that quick-task directory

## Shape (hygiene milestone pattern)

Per `feedback_hygiene_milestone_pattern.md` in user memory:
- **One phase** (Phase 1045 "Builder Smoke Polish")
- **Three sequential plans** grouped by severity tier
- **Single CTRL-01 batch gate** at end of phase
- Do NOT split into multiple phases

## Requirements

### BLOCKER

#### SP-01 — BulkActionBar Delete / Group / Ungroup buttons clipped by sidebar (was finding B-02)
**Outcome:** All BulkActionBar actions (Visibility, Group, Ungroup, Delete) are reachable from the UI when ≥ 2 layers are multi-selected; the bar layout works inside the 340 px sidebar at the default desktop viewport (1440 × 900).
**Files to investigate:** `frontend/src/components/builder/BulkActionBar.tsx`, `frontend/src/components/builder/UnifiedStackPanel.tsx` (mount point), `frontend/src/pages/MapBuilderPage.tsx` (sidebar shell with `aside class="border-e bg-background flex flex-col overflow-hidden"`).
**Likely fix:** Either span the bar across the full builder bottom (escape the sidebar `<aside>` clip), OR compact the buttons into an overflow menu when width < ~400 px. Prefer overflow menu unless the bar already lives outside the aside.
**Verify:** Playwright multi-select → click Delete; expect confirmation dialog. Also verify Group works on 2 vector layers; Ungroup on a folder-group row.

### MAJOR

#### SP-02 — Coord readout never updates lat/lng (was finding M-01)
**Outcome:** The top-right `<lat>° N · <lng>° W · z <zoom>` readout in the builder updates on every `move` / `moveend` event from MapLibre. After panning to a new region, the displayed lat/lng matches the actual map center.
**Files to investigate:** Search for `°N` or `°E` formatter near the builder map header (likely a `MapStatus*` component or inline JSX in `MapBuilderPage.tsx` / `BuilderMap.tsx`).
**Likely fix:** Subscribe the readout component to `map.on('move', …)` (or use the `move` event from the react-maplibre hook). Currently it reads a default viewState that never re-syncs.
**Verify:** Playwright pan/zoom → assert readout numbers match `map.getCenter()`.

#### SP-03 — DEM auto-add interaction with B-01 (was finding M-02)
**Outcome:** Verify the B-01 fix at commit `85738f1c` closes this finding (auto-fit-to-bbox fires while layers are missing from style). If still broken after B-01, escalate as a separate ticket; if resolved, mark closed inline with a one-line VERIFICATION.md justification.
**Likely fix:** None needed if B-01 fix closes it. If not, audit the auto-fit-bounds trigger ordering against the maplibre sync.
**Verify:** Smoke re-run: add a vector + DEM layer to a fresh map; data should be visible at the auto-fit zoom without reload.

#### SP-04 — Shift-click on layer rows replaces selection (was finding M-03)
**Outcome:** Shift-click on layer row B with row A already selected extends the selection to A + B (standard list-box range-select). ⌘/Ctrl-click still toggles individual rows.
**Files to investigate:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (keyboard / mouse selection handler).
**Likely fix:** Detect `e.shiftKey` in row click handler; compute range between last-clicked-anchor and current row; replace selection with that range.
**Verify:** Vitest unit test on the selection reducer + Playwright shift-click range test.

#### SP-05 — "Pending style preview" banner appears on untouched layer (was finding M-04)
**Outcome:** The "Pending style preview — Reflects this layer before save" banner is only shown when the layer has actual unsaved style mutations vs. its server state. Opening a layer's editor immediately after add does NOT show the banner.
**Files to investigate:** `frontend/src/components/builder/LayerStyleEditor.tsx` (the `stylePreviewStyle` helper + banner copy).
**Likely fix:** Gate the banner on a real dirty-tracking comparison (e.g. memoized deep-equal of editor draft vs. layer.paint/layout/style_config) rather than the existence of an editor draft.
**Verify:** Smoke re-check — add a layer, open its editor, banner should NOT be visible. Then change one paint value, banner SHOULD appear. Then Reset, banner SHOULD disappear.

### MINOR

#### SP-06 — Duplicate "Saved" badge + button in header (was finding m-01)
**Outcome:** Header shows EITHER a `[✓ Saved]` badge OR a `[Save] Saved` button — not both at once. When unsaved changes exist, button shows "Save" + dirty indicator; when saved, single visual state shown.
**Files to investigate:** `frontend/src/pages/MapBuilderPage.tsx` header region.
**Likely fix:** Remove the redundant badge; let the Save button carry the state.
**Verify:** DOM snapshot — only one element matching `Saved`/`Unsaved` text per state.

#### SP-07 — 3 quicklook 404s on search page (was finding m-02)
**Outcome:** Either (a) backfill quicklooks for the 3 older sample MultiPoint datasets, OR (b) frontend skips the request when the dataset's `thumbnail_status != 'ready'` (graceful skip without console error).
**Files to investigate:** `frontend/src/pages/SearchPage.tsx` quicklook fetch, `backend/app/modules/datasets/quicklook.py` (or equivalent generation task).
**Likely fix:** Frontend skip is lower-risk + future-proof. Add a check on `thumbnail_status` before issuing the GET. Backfill is fine if it's a one-line Celery enqueue.
**Verify:** Reload search page, console errors = 0.

#### SP-08 — /api/admin/ai-status/ polled aggressively (was finding m-03)
**Outcome:** `/api/admin/ai-status/` is called ≤ 2× over any 3-minute idle window (down from 11+). Result is cached/shared across components.
**Files to investigate:** Search for `ai-status` hook (likely `useAiStatus` or similar in `frontend/src/hooks/` or `api/`).
**Likely fix:** TanStack Query with `staleTime: 60_000` minimum; ensure single shared `queryKey: ['admin', 'ai-status']`; hoist to a context if multiple consumers.
**Verify:** Network audit — count ≤ 2 hits per 3 min idle.

#### SP-09 — /api/auth/refresh/ fires 3× concurrently (was finding m-04)
**Outcome:** Concurrent 401 → refresh attempts are de-duped behind a single in-flight promise. No more than one `/api/auth/refresh/` request fires per refresh cycle.
**Files to investigate:** `frontend/src/api/client.ts` auth interceptor.
**Likely fix:** Module-level `Promise` singleton that holds the in-flight refresh; subsequent callers await it; cleared on resolve/reject.
**Verify:** Trigger 3+ concurrent 401s (e.g. via expired tile tokens); network audit shows exactly 1 `auth/refresh/` POST.

#### SP-10 — Visibility toggle buttons missing aria-pressed (was finding m-05)
**Outcome:** All `<button aria-label="Toggle visibility for …">` toggles in `StackRow` (and basemap row) expose `aria-pressed={layer.visible}` so assistive tech can read the toggled state.
**Files to investigate:** `frontend/src/components/builder/StackRow.tsx`, `frontend/src/components/builder/UnifiedStackPanel.tsx` (basemap row).
**Likely fix:** Add `aria-pressed={layer.visible}` (or `!hidden`) to each toggle button.
**Verify:** Vitest a11y assertion + DOM query for `[aria-pressed]`.

#### SP-11 — /auth/login 307 trailing-slash redirect (was finding m-06)
**Outcome:** Either (a) define `/auth/login` without trailing slash so a body-preserving 200 is returned, OR (b) clearly document the trailing-slash requirement in the OpenAPI route description. Browser flow remains unaffected.
**Files to investigate:** `backend/app/modules/auth/router.py` login route definition.
**Likely fix:** Per the CLAUDE.md guidance, both shapes are legal — choose the no-trailing-slash form for external integrators. Decorator change only.
**Verify:** `curl -X POST http://localhost:8001/auth/login -H "content-type: application/x-www-form-urlencoded" -d 'username=admin&password=admin'` returns 200 (or 422 if data is wrong) — not 307.

### POLISH

#### SP-12 — Scale pane next to coord readout (was finding p-01)
**Outcome:** OPTIONAL. Either ship a small scale-bar / "1:288k" pane near the coord readout, OR explicitly defer with a one-line note in VERIFICATION.md.
**Files to investigate:** `frontend/src/pages/MapBuilderPage.tsx` map header.
**Likely fix:** Use MapLibre's `ScaleControl` or compute from `map.getZoom()` via a meter-per-pixel helper; skip if non-trivial.
**Verify:** Visual.

#### SP-13 — Basemap eye-toggle is disabled-but-button (was finding p-02)
**Outcome:** Replace the disabled `<button aria-label="Toggle visibility for Basemap · Positron">` with a non-interactive glyph (e.g. small lock icon or muted eye) + tooltip explaining "Basemap is always visible — use Remove basemap to hide."
**Files to investigate:** Basemap row in `UnifiedStackPanel.tsx`.
**Likely fix:** Conditional render: when `layer.is_basemap`, render `<span title="…">` instead of `<button disabled>`.
**Verify:** Visual + DOM snapshot.

#### SP-14 — Layer row hover affordance (was finding p-03)
**Outcome:** Hovering anywhere on a layer row body shows a `cursor: pointer` and a subtle hover background. Discoverability improves; click region behavior unchanged.
**Files to investigate:** `frontend/src/components/builder/StackRow.tsx` row container styles.
**Likely fix:** Add `hover:bg-[var(--surface-2)]` and `cursor-pointer` to the row container Tailwind classes.
**Verify:** Hover snapshot.

#### SP-15 — BulkActionBar persists across global Settings panel (was finding p-04)
**Outcome:** Opening the global ⚙ Settings panel either (a) dismisses the multi-select bar, OR (b) hides the bar visually while preserving the selection so it returns on close. Current behavior: bar pinned at the bottom while Settings is unrelated.
**Files to investigate:** `MapBuilderPage.tsx` selection state + scene rendering logic.
**Likely fix:** Hide the BulkActionBar when the global settings scene is active. Selection state can persist behind the scenes.
**Verify:** Multi-select 2 layers → open Settings → bar gone; close Settings → bar back.

#### SP-16 — Debounce thumbnail PUT (was finding p-05)
**Outcome:** Layer-add triggers AT MOST one `PUT /api/maps/<id>/thumbnail/` within a 500 ms window. Two back-to-back PUTs on every add is coalesced.
**Files to investigate:** Search for `thumbnail` PUT call in the builder save path.
**Likely fix:** Debounce the thumbnail capture by 500 ms using lodash debounce or a small inline helper.
**Verify:** Add a layer, network shows 1× PUT thumbnail/ (currently 2).

#### SP-17 — `＋ Add data` full-width plus character (was finding p-06)
**Outcome:** "+ Add data" button uses Lucide `<Plus />` icon consistent with other action buttons. No mixed typography.
**Files to investigate:** `UnifiedStackPanel.tsx` Add Data button.
**Likely fix:** Replace `"＋"` literal with `<Plus className="h-4 w-4" />`.
**Verify:** Visual + DOM check.

### HOUSEKEEPING

#### SP-18 — Delete test map `Smoke Check 2026-05-15`
**Outcome:** Map with UUID `a00b7e96-95b7-48d6-a911-57b97b767ebc` is deleted from the dev DB.
**Files to investigate:** none — operational task.
**Likely fix:** `curl -X DELETE` to the map endpoint with admin token, OR delete via UI.
**Verify:** `GET /api/maps/a00b7e96-…` returns 404.

## Success criteria

- 5 BLOCKER + MAJOR items: verifiable via Playwright smoke re-run of the same flows from the 2026-05-15 report
- 6 MINOR items: verifiable via network audit (ai-status ≤ 2/3min; auth refresh dedupe; 404 absence) or DOM/a11y assertion
- 6 POLISH + housekeeping items: verifiable visually or via simple selector check
- Single batch CTRL-01 gate produces VERIFICATION.md showing 18/18 pass
- Tag `v1009.1`, archive milestone

## Non-goals

- Re-architecting the BulkActionBar layout system beyond what SP-01 requires
- New widgets / new functionality beyond the items listed
- Adjusting the v1008/v1009 design tokens
- Backend Celery job changes beyond the SP-07 quicklook decision

## Hard rules

- No backward-compat shims (per `~/.claude/CLAUDE.md`)
- No blanket `git add -fA .planning/` (per `feedback_no_blanket_add_planning.md`)
- Run lint/typecheck locally before each commit (per `feedback_ci_local_first.md`)
- Fix reviewer findings inline rather than deferring (per `feedback_review_findings_inline.md`)
- Frontend stack is already up at `http://localhost:8080` — Vite HMR works, do NOT `docker compose build` again
- Single CTRL-01 batch gate; no per-plan CTRL gates (hygiene pattern)
