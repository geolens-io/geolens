# 1044-A11Y-WALKTHROUGH.md — Keyboard-Only Accessibility Walkthrough

**Phase:** 1044 (cross-cutting-closeout)
**Requirement:** POL-23
**Generated:** 2026-05-15

## How to verify

VoiceOver (macOS: Cmd+F5) or NVDA (Windows) recommended for full screen-reader verification.
The walkthrough is also runnable **without a screen reader** to verify focus management and visible UI behaviour — focus rings and cursor-not-allowed are visible cues that do not require AT.

Prerequisites:
- GeoLens running at `http://localhost:8080`
- At least one saved map with 2-3 overlay layers and a basemap group
- Admin or editor role (so the builder is accessible)

---

## Walkthrough A: Drag-from-catalog (keyboard only)

Verifies: `a11y.dragPickup`, `a11y.dragPosition`, `a11y.dragDropped`, `a11y.dragCancelled` aria-live announcements (POL-05, T-1040-10).

1. Open a map in the builder: navigate to `/maps/{id}` and wait for the layer stack to finish loading (sidebar shows existing layers).

2. Tab to the "+ Add data" button in the sidebar header and press `Enter` to open the Add Dataset modal.

3. Inside the modal, use `Tab` to move focus through the search results. Each dataset row has a grip handle with `aria-label="Drag to add to map"` (key: `search.dragHandle`). Tab until focus lands on a grip handle.

4. Press `Space` to pick up the item.
   - **Expected (with screen reader):** "Picked up [dataset name]. Use arrow keys to choose a position, Enter to drop, Escape to cancel." (`a11y.dragPickup`)
   - **Expected (visually):** The item visually lifts (drag pill appears).

5. Press `ArrowDown` one or more times to traverse drop targets in the layer stack.
   - **Expected (with screen reader):** "Current position: 1 of N", then "Current position: 2 of N", etc. (`a11y.dragPosition`). The announcement updates each time the over-target changes.

6. Press `Enter` (or `Space`) to drop the item at the current position.
   - **Expected (with screen reader):** "Dropped. [dataset name] added at position N." (`a11y.dragDropped`).
   - **Expected (visually):** The modal remains open (POL-05 — modal-stays-open contract); the layer appears in the stack; a toast confirms addition.

7. To cancel mid-drag instead: at step 4, after picking up, press `Escape`.
   - **Expected (with screen reader):** "Drop cancelled." (`a11y.dragCancelled`).
   - **Expected (visually):** The modal remains open; no layer is added to the stack.

---

## Walkthrough B: Multi-select bulk delete (keyboard only)

Verifies: listbox ARIA (`role="listbox"`, `aria-multiselectable="true"`, `aria-label="Map layers"`), Shift+Arrow extension, Escape clear, alertdialog autoFocus-on-Cancel (POL-06, POL-07, POL-10, POL-11, T-1044-07, T-1044-08).

1. With 3+ overlay layers in the stack, `Tab` into the layer listbox.
   - **Expected (with screen reader):** "Map layers, multi-select list" or similar — the listbox role is `role="listbox"` with `aria-label="Map layers"` and `aria-multiselectable="true"`. The screen reader announces the listbox name and role when entering.

2. Focus the first overlay row; the screen reader announces the row content and position within the listbox.

3. Press `Space` to toggle multi-selection on the focused row (`onCmdClick` — Space maps to Cmd-click which enters multi-select mode).
   - **Expected:** Row gains `aria-selected="true"`; a Checkbox becomes visible (POL-07).

4. Press `Shift+ArrowDown` to extend selection to the next row.
   - **Expected:** The next row gains `aria-selected="true"` (`onShiftClick` fires via the document keydown handler at UnifiedStackPanel.tsx:670-700). Repeat to extend further.

5. Tab to the bulk action toolbar (`role="toolbar"`, `aria-label` includes the selected count).

6. Tab to the "Delete" button and press `Space` (or `Enter`).
   - **Expected:** A confirmation dialog appears with `role="alertdialog"`.
   - **Expected (focus):** Focus auto-lands on the **Cancel** button (autoFocus, per Phase 1043-01 — T-1044-08 contract). A stray `Enter` at this point does NOT delete layers.

7. To confirm deletion: `Tab` once to the "Delete N layers" button, then `Space` or `Enter`.
   - **Expected:** The selected layers are removed; the BulkActionBar disappears; the listbox re-renders with remaining layers.

8. To cancel the confirmation: press `Escape` while the dialog is open.
   - **Expected:** Dialog closes; layers are preserved; focus returns to the bulk action toolbar.

9. To clear selection without deleting: while focused anywhere inside the listbox, press `Escape`.
   - **Expected:** `onClearSelection` fires (Escape handler at UnifiedStackPanel.tsx:670-700 — keyed on `selectedIds.size > 0`); the BulkActionBar disappears; all rows return to `aria-selected="false"`.

10. Basemap group boundary check (POL-11): with overlay rows selected, `Tab` to the basemap group row at the top of the stack.
    - **Expected:** Cursor shows as `cursor-not-allowed` (visual a11y signal). The basemap row does NOT receive `aria-selected="true"` even when overlay rows are selected. Cmd-click (or `Space`) on the basemap row does NOT add it to the selection set.

---

## Walkthrough C: Section transitions preserve focus + scroll (POL-18 carry-over)

Verifies: LayerEditorPanel navigation focus management.

1. With a basemap group in the stack, `Tab` to the basemap group row and press `Enter` to select it. The LayerEditorPanel flyout opens in the basemap-group scene.

2. `Tab` through the sublayer chips in the flyout. Press `Enter` on a sublayer chip to drill into the basemap-sublayer editing scene.

3. Press `Escape` (or click "Back to basemap" footer button) to navigate back to the basemap-group scene.
   - **Expected:** Focus returns to the originating sublayer chip.

4. Press `Escape` again to close the flyout or navigate back.
   - **Expected:** Focus returns to the basemap group row in the listbox; the vertical scroll position of the listbox is preserved (scroll is not reset to top on re-render).

---

## Source-of-truth references

| Reference | Location |
|-----------|----------|
| Listbox container with `role="listbox"` (basemap sublayers) | `frontend/src/components/builder/UnifiedStackPanel.tsx:780` |
| Main listbox + `aria-multiselectable` | `frontend/src/components/builder/UnifiedStackPanel.tsx:857-859` |
| Shift+Arrow handler + Escape clear (keydown listener on stackPanelRef) | `frontend/src/components/builder/UnifiedStackPanel.tsx:670-700` |
| Outside-mousedown clear effect | `frontend/src/components/builder/UnifiedStackPanel.tsx:650-659` |
| aria-live announcement region (sr-only div) | `frontend/src/pages/MapBuilderPage.tsx:879-886` |
| `announce()` + ZWS+timestamp re-fire pattern | `frontend/src/pages/MapBuilderPage.tsx:105-108` |
| Drag handlers calling `announce()` | `frontend/src/pages/MapBuilderPage.tsx:543-655` |
| BulkActionBar `role="alertdialog"` + Cancel `autoFocus` | `frontend/src/components/builder/BulkActionBar.tsx:140+156` |
| Grip handle `aria-label` (`search.dragHandle`) | `frontend/src/components/builder/DatasetSearchPanel.tsx:246+336` |
| a11y.* i18n keys (English copy) | `frontend/src/i18n/locales/en/builder.json` (a11y section) |

---

## Known limitations

- **dnd-kit KeyboardSensor and screen readers:** dnd-kit's KeyboardSensor uses `Space` to pick up, `Arrow` keys to traverse, and `Enter`/`Space` to drop. On macOS with VoiceOver enabled, VoiceOver may intercept `Space` before it reaches the application. VoiceOver users can press `Ctrl+Option+Space` to forward Space to the application layer (bypasses VoiceOver's virtual cursor). Alternatively, configure VoiceOver to "Use keyboard navigation" mode which passes keys through more aggressively.

- **Mobile (<800px) drill-down:** On viewport widths below 800px, the LayerEditorPanel opens as a Sheet overlay rather than an inline column. The keyboard nav path through the Sheet (focus trap, Escape to close) is a separate gesture pass deferred per Phase 1038 Test 4 mobile-defer comment in `frontend/e2e/builder-unified-stack.spec.ts:376-384`. Not covered in Walkthrough C above.

- **Aria-live tests 3-6 (pickup/drop/cancel content):** The vitest suite (`MapBuilderPage.a11y.test.tsx`) pins only the region's presence and initial state. Full announcement-content verification (pickup, position, dropped, cancelled strings) requires a real browser Playwright spec because dnd-kit PointerSensor needs actual pointer events with `distance >= 8px` to activate. See `frontend/e2e/builder-v1-5.spec.ts` (Phase 1044 Plan 03) for that coverage.
