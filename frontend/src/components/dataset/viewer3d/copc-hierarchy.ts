import type { Hierarchy } from 'copc';
import {
  MAX_HIERARCHY_BYTES,
  MAX_HIERARCHY_PAGES,
  MAX_HIERARCHY_PAGE_DEPTH,
  MAX_RANGE_BYTES,
  MAX_SELECTED_NODES,
  POINT_BUDGET,
} from './copc-limits';

type LoadPage = (page: Hierarchy.Page) => Promise<Hierarchy.Subtree>;

const keyDepth = (key: string): number => {
  const depth = Number(key.split('-')[0]);
  return Number.isSafeInteger(depth) && depth >= 0 ? depth : Number.POSITIVE_INFINITY;
};

/** Whether the nodes known above `depth` already fill the point or node budget, so deeper ones would not be drawn. */
function selectionFilledAbove(nodes: Hierarchy.Node.Map, depth: number): boolean {
  let points = 0;
  let count = 0;
  for (const [key, node] of Object.entries(nodes)) {
    if (!node || keyDepth(key) >= depth) continue;
    if (Number.isSafeInteger(node.pointCount) && node.pointCount > 0) points += node.pointCount;
    count += 1;
  }
  return points >= POINT_BUDGET || count >= MAX_SELECTED_NODES;
}

/**
 * The root page's nodes plus those of the child pages the selection can reach.
 * Pages are read coarsest first, only while shallower nodes leave budget for
 * deeper ones, and within a page count, byte and nesting cap. A page that is
 * malformed, repeated, outside the file or that fails to load is skipped, so
 * the result is never smaller than what the root page lists.
 */
export async function loadHierarchyNodes(
  root: Hierarchy.Page,
  loadPage: LoadPage,
  fileSize: number | null,
): Promise<Hierarchy.Node.Map> {
  const rootSubtree = await loadPage(root);
  const nodes: Hierarchy.Node.Map = { ...rootSubtree.nodes };
  const seen = new Set<number>([root.pageOffset]);
  const frontier: { depth: number; nesting: number; page: Hierarchy.Page }[] = [];
  const enqueue = (pages: Hierarchy.Page.Map, nesting: number) => {
    if (nesting > MAX_HIERARCHY_PAGE_DEPTH) return;
    for (const [key, page] of Object.entries(pages)) {
      if (page) frontier.push({ depth: keyDepth(key), nesting, page });
    }
  };
  enqueue(rootSubtree.pages ?? {}, 1);

  let reads = 0;
  let bytes = 0;
  while (frontier.length > 0 && reads < MAX_HIERARCHY_PAGES) {
    frontier.sort((a, b) => a.depth - b.depth);
    const { depth, nesting, page } = frontier.shift()!;
    const { pageOffset, pageLength } = page;
    if (!Number.isSafeInteger(pageOffset) || pageOffset < 0 || seen.has(pageOffset)) continue;
    if (!Number.isSafeInteger(pageLength) || pageLength <= 0 || pageLength > MAX_RANGE_BYTES) continue;
    if (fileSize !== null && pageOffset + pageLength > fileSize) continue;
    if (bytes + pageLength > MAX_HIERARCHY_BYTES) continue;
    if (selectionFilledAbove(nodes, depth)) continue;
    seen.add(pageOffset);
    reads += 1;
    bytes += pageLength;
    try {
      const subtree = await loadPage(page);
      for (const [key, node] of Object.entries(subtree.nodes)) if (!(key in nodes)) nodes[key] = node;
      enqueue(subtree.pages ?? {}, nesting + 1);
    } catch {
      // A bad page leaves the coarser nodes already known.
    }
  }
  return nodes;
}
