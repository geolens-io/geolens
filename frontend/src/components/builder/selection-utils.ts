/**
 * Phase 1045 SP-04 — selection-utils
 *
 * Pure helper that computes the next layer-row selection state from a click
 * event. Extracted so it can be unit-tested without rendering the panel.
 *
 * Behavior contract (matches macOS Finder list-box):
 *   - Plain click row E      → selection = {E},                anchor = E
 *   - Cmd/Ctrl-click row D   → selection toggles D,            anchor = D
 *   - Shift-click row B      → selection = {anchor..B},        anchor unchanged
 *   - Shift-click without an anchor falls back to plain-click semantics
 *     (selection = {row}, anchor = row).
 *
 * `rows` is the ordered list of selectable row ids in render order; basemap
 * group + sublayer ids must NOT be included. Cross-boundary range-select is
 * blocked at the caller (boundary guard runs first).
 */

export interface ClickModifiers {
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
}

export interface NextSelection {
  selection: Set<string>;
  anchor: string | null;
}

export function computeNextSelection(
  rows: readonly string[],
  clickedId: string,
  modifiers: ClickModifiers,
  currentSelection: ReadonlySet<string>,
  anchor: string | null,
): NextSelection {
  // Cmd/Ctrl: toggle individual + move anchor to the toggled row.
  if (modifiers.metaKey || modifiers.ctrlKey) {
    const next = new Set(currentSelection);
    if (next.has(clickedId)) {
      next.delete(clickedId);
    } else {
      next.add(clickedId);
    }
    return { selection: next, anchor: clickedId };
  }

  // Shift: range-extend from anchor to clicked row. Anchor stays put so
  // subsequent shift-clicks extend further from the original origin point.
  if (modifiers.shiftKey) {
    if (!anchor) {
      // No anchor recorded yet — treat as plain click.
      return { selection: new Set([clickedId]), anchor: clickedId };
    }
    const anchorIdx = rows.indexOf(anchor);
    const clickedIdx = rows.indexOf(clickedId);
    if (anchorIdx < 0 || clickedIdx < 0) {
      // Anchor or target not in selectable list — fall back to plain click.
      return { selection: new Set([clickedId]), anchor: clickedId };
    }
    const lo = Math.min(anchorIdx, clickedIdx);
    const hi = Math.max(anchorIdx, clickedIdx);
    return {
      selection: new Set(rows.slice(lo, hi + 1)),
      anchor, // unchanged
    };
  }

  // Plain click: clear existing selection, select only this row, move anchor.
  return { selection: new Set([clickedId]), anchor: clickedId };
}
