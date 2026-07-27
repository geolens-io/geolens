/**
 * Phase 1045 SP-04 — selection-utils tests
 *
 * Pure-function unit tests for `computeNextSelection`. No React, no DOM.
 */

import { describe, it, expect } from 'vitest';
import { computeNextSelection, computeSelectableRowIds } from '../selection-utils';
import type { MapLayerResponse } from '@/types/api';

const ROWS = ['A', 'B', 'C', 'D', 'E'];

const PLAIN = { shiftKey: false, metaKey: false, ctrlKey: false };
const SHIFT = { shiftKey: true, metaKey: false, ctrlKey: false };
const META = { shiftKey: false, metaKey: true, ctrlKey: false };
const CTRL = { shiftKey: false, metaKey: false, ctrlKey: true };

describe('computeNextSelection — plain click', () => {
  it('plain click selects only the clicked row and moves anchor', () => {
    const result = computeNextSelection(ROWS, 'C', PLAIN, new Set(), null);
    expect(Array.from(result.selection)).toEqual(['C']);
    expect(result.anchor).toBe('C');
  });

  it('plain click clears any existing multi-selection', () => {
    const result = computeNextSelection(ROWS, 'E', PLAIN, new Set(['A', 'B']), 'A');
    expect(Array.from(result.selection)).toEqual(['E']);
    expect(result.anchor).toBe('E');
  });
});

describe('computeNextSelection — cmd/ctrl click', () => {
  it('cmd-click on unselected row adds row + moves anchor to it', () => {
    const result = computeNextSelection(ROWS, 'C', META, new Set(['A']), 'A');
    expect(result.selection).toEqual(new Set(['A', 'C']));
    expect(result.anchor).toBe('C');
  });

  it('cmd-click on selected row removes row + moves anchor to it', () => {
    const result = computeNextSelection(ROWS, 'B', META, new Set(['A', 'B']), 'A');
    expect(result.selection).toEqual(new Set(['A']));
    expect(result.anchor).toBe('B');
  });

  it('ctrl-click behaves identically to meta-click', () => {
    const result = computeNextSelection(ROWS, 'D', CTRL, new Set(['A']), 'A');
    expect(result.selection).toEqual(new Set(['A', 'D']));
    expect(result.anchor).toBe('D');
  });
});

describe('computeNextSelection — shift click (range-select)', () => {
  it('shift-click downwards extends range A..D and keeps anchor at A', () => {
    const result = computeNextSelection(ROWS, 'D', SHIFT, new Set(['A']), 'A');
    expect(Array.from(result.selection)).toEqual(['A', 'B', 'C', 'D']);
    expect(result.anchor).toBe('A');
  });

  it('shift-click upwards extends range C..A and keeps anchor at C', () => {
    const result = computeNextSelection(ROWS, 'A', SHIFT, new Set(['C']), 'C');
    expect(Array.from(result.selection)).toEqual(['A', 'B', 'C']);
    expect(result.anchor).toBe('C');
  });

  it('shift-click without an anchor falls back to plain-click semantics', () => {
    const result = computeNextSelection(ROWS, 'D', SHIFT, new Set(), null);
    expect(Array.from(result.selection)).toEqual(['D']);
    expect(result.anchor).toBe('D');
  });

  it('shift-click after a range-extend continues to extend from the ORIGINAL anchor', () => {
    // Click A — selection {A}, anchor A
    const first = computeNextSelection(ROWS, 'A', PLAIN, new Set(), null);
    // Shift-click C — selection {A,B,C}, anchor still A
    const second = computeNextSelection(ROWS, 'C', SHIFT, first.selection, first.anchor);
    expect(Array.from(second.selection)).toEqual(['A', 'B', 'C']);
    expect(second.anchor).toBe('A');
    // Shift-click E — selection {A,B,C,D,E}, anchor still A
    const third = computeNextSelection(ROWS, 'E', SHIFT, second.selection, second.anchor);
    expect(Array.from(third.selection)).toEqual(['A', 'B', 'C', 'D', 'E']);
    expect(third.anchor).toBe('A');
  });

  it('shift-click REPLACES the existing selection with the range (does not add to it)', () => {
    // Start with stale extra selection — shift-click should drop it.
    const result = computeNextSelection(ROWS, 'C', SHIFT, new Set(['A', 'E']), 'A');
    expect(Array.from(result.selection)).toEqual(['A', 'B', 'C']);
    expect(result.anchor).toBe('A');
  });

  it('shift-click on an unknown row falls back to plain-click semantics', () => {
    const result = computeNextSelection(ROWS, 'Z', SHIFT, new Set(['A']), 'A');
    expect(Array.from(result.selection)).toEqual(['Z']);
    expect(result.anchor).toBe('Z');
  });

  it('shift-click when anchor is no longer in rows falls back to plain-click semantics', () => {
    const result = computeNextSelection(ROWS, 'C', SHIFT, new Set(['gone']), 'gone');
    expect(Array.from(result.selection)).toEqual(['C']);
    expect(result.anchor).toBe('C');
  });
});

// fix(#771): selectableRowIds must mirror the RENDERED row set — children of
// collapsed groups and rows hidden by the layer search are not selectable, so
// a shift-click range can never act on rows the user cannot see.
describe('computeSelectableRowIds', () => {
  function makeRow(overrides: {
    id: string;
    display_name?: string | null;
    dataset_name?: string;
    layer_type?: string | null;
    parent_group_id?: string | null;
  }): MapLayerResponse {
    return {
      id: overrides.id,
      display_name: overrides.display_name ?? null,
      dataset_name: overrides.dataset_name ?? overrides.id,
      layer_type: overrides.layer_type ?? 'vector_geolens',
      parent_group_id: overrides.parent_group_id ?? null,
    } as unknown as MapLayerResponse;
  }

  // Stack: [group G ("Roads") with children c1 ("Streets") + c2 ("Rivers"), loose L ("Parcels")]
  const group = makeRow({ id: 'G', display_name: 'Roads', layer_type: 'group:folder' });
  const child1 = makeRow({ id: 'c1', display_name: 'Streets', parent_group_id: 'G' });
  const child2 = makeRow({ id: 'c2', display_name: 'Rivers', parent_group_id: 'G' });
  const loose = makeRow({ id: 'L', display_name: 'Parcels' });
  const stack = [group, child1, child2, loose];

  it('returns render order (group, its children, loose rows) with no search and an expanded group', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: true } }, '')).toEqual([
      'G', 'c1', 'c2', 'L',
    ]);
  });

  it('excludes children of a collapsed group (they are not rendered)', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: false } }, '')).toEqual(['G', 'L']);
    // groupMeta absence means collapsed (matches the panel's `?? false` default)
    expect(computeSelectableRowIds(stack, {}, '')).toEqual(['G', 'L']);
  });

  it('excludes rows hidden by the layer search', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: true } }, 'parcel')).toEqual(['L']);
  });

  it('a child match keeps the group header and only the matching children', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: true } }, 'streets')).toEqual([
      'G', 'c1',
    ]);
  });

  it('a group-name match keeps every child of the expanded group', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: true } }, 'roads')).toEqual([
      'G', 'c1', 'c2',
    ]);
  });

  it('a child match inside a COLLAPSED group keeps only the group header', () => {
    expect(computeSelectableRowIds(stack, { G: { expanded: false } }, 'streets')).toEqual(['G']);
  });

  it('falls back to dataset_name when display_name is null (matches the search input behavior)', () => {
    const unnamed = makeRow({ id: 'U', display_name: null, dataset_name: 'Unnamed dataset' });
    expect(computeSelectableRowIds([unnamed, loose], {}, 'unnamed')).toEqual(['U']);
  });
});
