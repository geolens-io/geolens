import type { Hierarchy } from 'copc';
import { selectionFullAbove } from './copc-select';
import {
  MAX_HIERARCHY_BYTES,
  MAX_HIERARCHY_PAGES,
  MAX_HIERARCHY_PAGE_DEPTH,
  MAX_HIERARCHY_REFERENCES,
  MAX_RANGE_BYTES,
  POINT_BUDGET,
} from './copc-limits';

type LoadPage = (page: Hierarchy.Page) => Promise<Hierarchy.Subtree>;

const keyDepth = (key: string): number => {
  const depth = Number(key.split('-')[0]);
  return Number.isSafeInteger(depth) && depth >= 0 ? depth : Number.POSITIVE_INFINITY;
};

/**
 * The root page's nodes plus those of the child pages the selection can reach.
 * Pages are read coarsest first, only while shallower nodes leave budget for
 * deeper ones, and within a page count, byte, nesting and reference cap. A page
 * that is malformed, repeated, outside the file or that fails to load is
 * skipped, so the result is never smaller than what the root page lists.
 */
export async function loadHierarchyNodes(
  root: Hierarchy.Page,
  loadPage: LoadPage,
  fileSize: number | null,
  recordLength: number,
): Promise<Hierarchy.Node.Map> {
  const rootSubtree = await loadPage(root);
  const nodes: Hierarchy.Node.Map = { ...rootSubtree.nodes };
  const seen = new Set<number>([root.pageOffset]);
  // Sorted deepest first so the coarsest page pops off the end in O(1).
  let frontier: { depth: number; nesting: number; page: Hierarchy.Page }[] = [];
  let references = 0;
  const enqueue = (pages: Hierarchy.Page.Map | undefined, nesting: number) => {
    if (nesting > MAX_HIERARCHY_PAGE_DEPTH || !pages) return;
    const batch: typeof frontier = [];
    for (const [key, page] of Object.entries(pages)) {
      if (page && references + batch.length < MAX_HIERARCHY_REFERENCES) {
        batch.push({ depth: keyDepth(key), nesting, page });
      }
    }
    references += batch.length;
    frontier = frontier.concat(batch).sort((a, b) => b.depth - a.depth);
  };
  enqueue(rootSubtree.pages, 1);

  let reads = 0;
  let bytes = 0;
  while (frontier.length > 0 && reads < MAX_HIERARCHY_PAGES) {
    const { depth, nesting, page } = frontier.pop()!;
    const { pageOffset, pageLength } = page;
    if (!Number.isSafeInteger(pageOffset) || pageOffset < 0 || seen.has(pageOffset)) continue;
    if (!Number.isSafeInteger(pageLength) || pageLength <= 0 || pageLength > MAX_RANGE_BYTES) continue;
    if (fileSize !== null && pageOffset + pageLength > fileSize) continue;
    if (bytes + pageLength > MAX_HIERARCHY_BYTES) continue;
    // Every remaining page is at least this deep, so a full selection ends the walk.
    if (selectionFullAbove(nodes, depth, POINT_BUDGET, recordLength, fileSize)) break;
    seen.add(pageOffset);
    reads += 1;
    bytes += pageLength;
    try {
      const subtree = await loadPage(page);
      for (const [key, node] of Object.entries(subtree.nodes)) if (!(key in nodes)) nodes[key] = node;
      enqueue(subtree.pages, nesting + 1);
    } catch {
      // A bad page leaves the coarser nodes already known.
    }
  }
  return nodes;
}
