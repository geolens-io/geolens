/**
 * Phase 1045 SP-04 — selection-utils tests
 *
 * Pure-function unit tests for `computeNextSelection`. No React, no DOM.
 */

import { describe, it, expect } from 'vitest';
import { computeNextSelection } from '../selection-utils';

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
