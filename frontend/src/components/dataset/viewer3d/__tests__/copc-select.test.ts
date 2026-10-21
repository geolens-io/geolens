import type { Hierarchy } from 'copc';
import { describe, expect, it } from 'vitest';
import { MAX_RANGE_BYTES, MAX_SELECTED_BYTES, MAX_SELECTED_NODES, POINT_BUDGET } from '../copc-limits';
import { selectNodes } from '../copc-select';

const node = (pointCount: number, offset = 1000, length = 500): Hierarchy.Node => ({
  pointCount,
  pointDataOffset: offset,
  pointDataLength: length,
});
const map = (entries: Record<string, Hierarchy.Node>) => entries as Hierarchy.Node.Map;

describe('selectNodes', () => {
  it('takes the coarsest nodes first until the point budget is spent', () => {
    const picked = selectNodes(
      map({ '2-0-0-0': node(400), '0-0-0-0': node(300), '1-0-0-0': node(300), '3-0-0-0': node(10) }),
      1000,
      34,
      null,
    );
    expect(picked.map(([key]) => key)).toEqual(['0-0-0-0', '1-0-0-0', '2-0-0-0']);
  });

  it('selects a single node holding more than a million points, up to the budget', () => {
    const picked = selectNodes(map({ '0-0-0-0': node(1_500_000) }), 2_000_000, 34, null);
    expect(picked).toHaveLength(1);
  });

  it('keeps a load inside its read budget when the hierarchy has many small nodes', () => {
    const many = Object.fromEntries(
      Array.from({ length: MAX_SELECTED_NODES + 50 }, (_, i) => [`3-${i}-0-0`, node(10, 1000 + i, 5)]),
    );
    expect(selectNodes(map(many), POINT_BUDGET, 34, null)).toHaveLength(MAX_SELECTED_NODES);
  });

  it('keeps a load inside its byte budget when nodes are large', () => {
    const big = 60 * 1024 * 1024;
    const picked = selectNodes(
      map({ '0-0-0-0': node(100, 1000, big), '1-0-0-0': node(100, 1000, big), '1-1-0-0': node(100, 1000, big), '1-0-1-0': node(100, 1000, big) }),
      POINT_BUDGET,
      34,
      null,
    );
    expect(picked.length * big).toBeLessThanOrEqual(MAX_SELECTED_BYTES);
    expect(picked.length).toBe(3);
  });

  it('accepts a node whose compressed chunk is between 16 and 64 MiB', () => {
    expect(selectNodes(map({ '0-0-0-0': node(100, 1000, 40 * 1024 * 1024) }), POINT_BUDGET, 34, null)).toHaveLength(1);
  });

  it('stops at the first node that would pass the budget', () => {
    const picked = selectNodes(map({ '0-0-0-0': node(600), '1-0-0-0': node(600), '2-0-0-0': node(1) }), 1000, 34, null);
    expect(picked.map(([key]) => key)).toEqual(['0-0-0-0']);
  });

  it.each([
    ['a negative count', node(-1)],
    ['a zero count', node(0)],
    ['a fractional count', node(1.5)],
    ['a non-finite count', node(Number.POSITIVE_INFINITY)],
    ['a count past the node cap', node(POINT_BUDGET + 1)],
    ['a negative offset', node(10, -5)],
    ['a zero length', node(10, 1000, 0)],
    ['a length past the read cap', node(10, 1000, MAX_RANGE_BYTES + 1)],
    ['a range past the file size', node(10, 9900, 500)],
  ])('drops %s', (_label, bad) => {
    expect(selectNodes(map({ '0-0-0-0': bad }), 1_000_000, 34, 10_000)).toEqual([]);
  });

  it('drops a node whose decoded size would pass the cap, whatever its point count', () => {
    expect(selectNodes(map({ '0-0-0-0': node(POINT_BUDGET) }), 10_000_000, 65535, null)).toEqual([]);
  });

  it('drops malformed keys and an unusable record length', () => {
    expect(selectNodes(map({ 'x-0-0-0': node(10), '0-0-0': node(10) }), 1000, 34, null)).toEqual([]);
    expect(selectNodes(map({ '0-0-0-0': node(10) }), 1000, 0, null)).toEqual([]);
    expect(selectNodes(map({ '0-0-0-0': node(10) }), 1000, Number.NaN, null)).toEqual([]);
  });
});
