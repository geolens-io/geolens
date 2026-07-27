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

import { getParentGroupId } from '@/components/builder/folder-groups';
import { isFolderGroupLayer } from '@/lib/layer-capabilities';
import type { MapLayerResponse } from '@/types/api';

export interface ClickModifiers {
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
}

/** Case-insensitive substring match on display_name falling back to
 *  dataset_name. An empty (or whitespace-only) query always matches.
 *  Single source of truth shared by UnifiedStackPanel's row rendering and
 *  computeSelectableRowIds below — the two must never disagree. */
export function layerMatchesSearch(layer: MapLayerResponse, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  return (layer.display_name ?? layer.dataset_name ?? '').toLowerCase().includes(q);
}

/**
 * fix(#771): the ordered list of row ids the stack actually RENDERS — children
 * of collapsed groups and rows hidden by the layer search are excluded. The raw
 * flat layer array previously fed shift-click range selection directly, so a
 * range could sweep up rows the user cannot see and bulk delete/visibility/
 * opacity then acted on them. Mirrors UnifiedStackPanel's render plan exactly
 * (the panel consumes this same helper for its row-skip decisions):
 *   - group row: rendered unless a search is active and neither its name nor
 *     any child matches;
 *   - group children: rendered only while the group is expanded, and (under
 *     search) only when the group name or the child itself matches;
 *   - loose row: rendered unless a search is active and it does not match.
 */
export function computeSelectableRowIds(
  layers: MapLayerResponse[],
  groupMeta: Record<string, { expanded: boolean }>,
  searchQuery: string,
): string[] {
  const isSearchActive = searchQuery.trim() !== '';
  const childrenByGroup = new Map<string, MapLayerResponse[]>();
  for (const layer of layers) {
    const parentId = getParentGroupId(layer);
    if (parentId) {
      const siblings = childrenByGroup.get(parentId);
      if (siblings) siblings.push(layer);
      else childrenByGroup.set(parentId, [layer]);
    }
  }

  const ids: string[] = [];
  for (const layer of layers) {
    if (getParentGroupId(layer)) continue; // children are emitted with their group

    if (isFolderGroupLayer(layer)) {
      const children = childrenByGroup.get(layer.id) ?? [];
      const groupNameMatches = layerMatchesSearch(layer, searchQuery);
      const anyChildMatches = children.some((child) => layerMatchesSearch(child, searchQuery));
      if (isSearchActive && !groupNameMatches && !anyChildMatches) continue;
      ids.push(layer.id);
      if (!(groupMeta[layer.id]?.expanded ?? false)) continue;
      for (const child of children) {
        if (isSearchActive && !groupNameMatches && !layerMatchesSearch(child, searchQuery)) continue;
        ids.push(child.id);
      }
      continue;
    }

    if (isSearchActive && !layerMatchesSearch(layer, searchQuery)) continue;
    ids.push(layer.id);
  }
  return ids;
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
