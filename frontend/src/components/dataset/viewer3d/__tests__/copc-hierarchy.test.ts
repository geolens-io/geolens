import type { Hierarchy } from 'copc';
import { describe, expect, it, vi } from 'vitest';
import { MAX_HIERARCHY_BYTES, MAX_HIERARCHY_PAGES, POINT_BUDGET } from '../copc-limits';
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
    const nodes = await loadHierarchyNodes(root, load, null);
    expect(Object.keys(nodes).sort()).toEqual(['0-0-0-0', '2-0-0-0']);
  });

  it('stops at the page-count budget', async () => {
    const pages = Object.fromEntries(Array.from({ length: MAX_HIERARCHY_PAGES + 20 }, (_, i) => [`3-${i}-0-0`, page(1000 + i)]));
    const subtrees: Subtrees = { 10: { nodes: { '0-0-0-0': node() }, pages } };
    for (let i = 0; i < MAX_HIERARCHY_PAGES + 20; i++) subtrees[1000 + i] = { nodes: {}, pages: {} };
    const load = loader(subtrees);
    await loadHierarchyNodes(root, load, null);
    expect(load).toHaveBeenCalledTimes(1 + MAX_HIERARCHY_PAGES);
  });

  it('stops at the page byte budget', async () => {
    const big = Math.floor(MAX_HIERARCHY_BYTES / 2) + 1;
    const load = loader({
      10: { nodes: {}, pages: { '1-0-0-0': page(200, big), '1-1-0-0': page(300, big) } },
      200: { nodes: { '2-0-0-0': node() }, pages: {} },
      300: { nodes: { '2-1-0-0': node() }, pages: {} },
    });
    const nodes = await loadHierarchyNodes(root, load, null);
    expect(Object.keys(nodes)).toEqual(['2-0-0-0']);
  });

  it('does not read pages when shallower nodes already fill the point budget', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node(POINT_BUDGET) }, pages: { '1-0-0-0': page(200) } },
      200: { nodes: { '2-0-0-0': node() }, pages: {} },
    });
    await loadHierarchyNodes(root, load, null);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('terminates on a page that references itself or the root', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(200) } },
      200: { nodes: { '2-0-0-0': node() }, pages: { '2-0-0-0': page(200), '2-1-0-0': page(10) } },
    });
    const nodes = await loadHierarchyNodes(root, load, null);
    expect(load).toHaveBeenCalledTimes(2);
    expect(Object.keys(nodes).sort()).toEqual(['0-0-0-0', '2-0-0-0']);
  });

  it('keeps the root nodes when a child page fails to load', async () => {
    const load = loader({ 10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(200) } } });
    const nodes = await loadHierarchyNodes(root, load, null);
    expect(Object.keys(nodes)).toEqual(['0-0-0-0']);
  });

  it('skips a page outside the file', async () => {
    const load = loader({
      10: { nodes: { '0-0-0-0': node() }, pages: { '1-0-0-0': page(900, 500) } },
      900: { nodes: { '2-0-0-0': node() }, pages: {} },
    });
    await loadHierarchyNodes(root, load, 1000);
    expect(load).toHaveBeenCalledTimes(1);
  });
});
