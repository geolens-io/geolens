import type { Hierarchy } from 'copc';
import { describe, expect, it, vi } from 'vitest';
import { MAX_HIERARCHY_BYTES, MAX_HIERARCHY_PAGES, MAX_HIERARCHY_REFERENCES, MAX_SELECTED_NODES, POINT_BUDGET } from '../copc-limits';
import { loadHierarchyNodes } from '../copc-hierarchy';

const node = (pointCount = 10): Hierarchy.Node => ({ pointCount, pointDataOffset: 1000, pointDataLength: 50 });
const page = (pageOffset: number, pageLength = 100): Hierarchy.Page => ({ pageOffset, pageLength });
const root = page(10);

type Subtrees = Record<number, Hierarchy.Subtree>;
const loader = (subtrees: Subtrees) =>
  vi.fn(async (p: Hierarchy.Page) => {
    const found = subtrees[p.pageOffset];
    if (!found) throw new Error('read failed');
    return found;
  });

describe('loadHierarchyNodes', () => {
  it('adds the nodes of a page the root page references', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(200) } },
      200: { nodes: { '2-0-0-0': node() }, pages: {} },
    });
    const nodes = await loadHierarchyNodes(root, load, null, 34);
    expect(Object.keys(nodes).sort()).toEqual(['0-0-0-0', '2-0-0-0']);
  });

  it('stops at the page-count budget', async () => {
    const pages = Object.fromEntries(Array.from({ length: MAX_HIERARCHY_PAGES + 20 }, (_, i) => [`3-${i}-0-0`, page(1000 + i)]));
    const subtrees: Subtrees = { 10: { nodes: { '0-0-0-0': node() }, pages } };
    for (let i = 0; i < MAX_HIERARCHY_PAGES + 20; i++) subtrees[1000 + i] = { nodes: {}, pages: {} };
    const load = loader(subtrees);
    await loadHierarchyNodes(root, load, null, 34);
    expect(load).toHaveBeenCalledTimes(1 + MAX_HIERARCHY_PAGES);
  });

  it('stops at the page byte budget', async () => {
    const big = Math.floor(MAX_HIERARCHY_BYTES / 2) + 1;
    const load = loader({
      10: { nodes: {}, pages: { '1-0-0-0': page(200, big), '1-1-0-0': page(300, big) } },
      200: { nodes: { '2-0-0-0': node() }, pages: {} },
      300: { nodes: { '2-1-0-0': node() }, pages: {} },
    });
    const nodes = await loadHierarchyNodes(root, load, null, 34);
    expect(Object.keys(nodes)).toHaveLength(1);
  });

  it('does not read pages when shallower nodes already fill the point budget', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node(POINT_BUDGET) }, pages: { '1-0-0-0': page(200) } },
      200: { nodes: { '2-0-0-0': node() }, pages: {} },
    });
    await loadHierarchyNodes(root, load, null, 34);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('terminates on a page that references itself or the root', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(200) } },
      200: { nodes: { '2-0-0-0': node() }, pages: { '2-0-0-0': page(200), '2-1-0-0': page(10) } },
    });
    const nodes = await loadHierarchyNodes(root, load, null, 34);
    expect(load).toHaveBeenCalledTimes(2);
    expect(Object.keys(nodes).sort()).toEqual(['0-0-0-0', '2-0-0-0']);
  });

  it('keeps the root nodes when a child page fails to load', async () => {
    const load = loader({ 10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(200) } } });
    const nodes = await loadHierarchyNodes(root, load, null, 34);
    expect(Object.keys(nodes)).toEqual(['0-0-0-0']);
  });

  it('skips a page outside the file', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(900, 500) } },
      900: { nodes: { '2-0-0-0': node() }, pages: {} },
    });
    await loadHierarchyNodes(root, load, 1000, 34);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('draws on child pages when the shallow entries are all unusable', async () => {
    const empties = Object.fromEntries(Array.from({ length: MAX_SELECTED_NODES + 50 }, (_, i) => [`1-${i}-0-0`, node(0)]));
    const rejected = Object.fromEntries(
      Array.from({ length: MAX_SELECTED_NODES + 50 }, (_, i) => [`1-${i}-1-0`, { ...node(), pointDataLength: -1 }]),
    );
    const load = loader({
      10: { nodes: { '0-0-0-0': node(), ...empties, ...rejected }, pages: { '2-0-0-0': page(200) } },
      200: { nodes: { '3-0-0-0': node() }, pages: {} },
    });
    const nodes = await loadHierarchyNodes(root, load, null, 34);
    expect(nodes['3-0-0-0']).toBeDefined();
  });

  it.each([
    ['repeated offsets', () => page(10)],
    ['malformed pages', () => page(Number.NaN)],
    ['pages outside the file', () => page(5_000_000)],
    ['pages over the byte cap', () => page(500, MAX_HIERARCHY_BYTES + 1)],
  ])('bounds the work on a wide hierarchy of %s', async (_name, make) => {
    const pages = Object.fromEntries(Array.from({ length: 50_000 }, (_, i) => [`3-${i}-0-0`, make()]));
    const load = loader({ 10: { nodes: { '0-0-0-0': node() }, pages } });
    const start = performance.now();
    await loadHierarchyNodes(root, load, 1_000_000, 34);
    expect(performance.now() - start).toBeLessThan(500);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('ignores references past the reference cap', async () => {
    const pages = Object.fromEntries(
      Array.from({ length: MAX_HIERARCHY_REFERENCES + 10 }, (_, i) => [`${i < MAX_HIERARCHY_REFERENCES ? 9 : 1}-${i}-0-0`, page(1000 + i)]),
    );
    const load = loader({ 10: { nodes: {}, pages } });
    await loadHierarchyNodes(root, load, null, 34);
    const read = load.mock.calls.map(([p]) => p.pageOffset);
    expect(read.every((o) => o === 10 || o < 1000 + MAX_HIERARCHY_REFERENCES)).toBe(true);
  });
});
